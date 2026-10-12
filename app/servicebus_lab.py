"""Práctica independiente con una cola real de Azure Service Bus."""
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from azure.identity import AzureCliCredential
from azure.servicebus import (ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode,
                              ServiceBusSubQueue, TransportType)
from azure.core.exceptions import AzureError
from azure.servicebus.exceptions import MessageLockLostError


def replay_message(client, queue, receiver, message):
    # Los mensajes de este laboratorio tienen cuerpo AMQP DATA.
    copy = ServiceBusMessage(b''.join(message.body), message_id=message.message_id,
                             content_type=message.content_type,
                             correlation_id=message.correlation_id,
                             application_properties=message.application_properties)
    with client.get_queue_sender(queue) as sender:
        sender.send_messages(copy)
    # No confirmar antes de enviar: un fallo de envío debe conservar el original.
    receiver.complete_message(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['send', 'send-blob', 'send-invoice', 'resend-invoice', 'receive', 'fail', 'peek', 'dlq', 'replay', 'expire', 'renew'])
    parser.add_argument('--document-id', type=UUID, help='Documento existente para resend-invoice')
    parser.add_argument('--file', type=Path, help='TXT UTF-8 de hasta 12000 caracteres para send-invoice')
    args = parser.parse_args()
    if args.action == 'resend-invoice' and args.document_id is None:
        parser.error('resend-invoice requiere --document-id')
    if args.action != 'resend-invoice' and args.document_id is not None:
        parser.error('--document-id solo se utiliza con resend-invoice')
    if args.file is not None and args.action != 'send-invoice':
        parser.error('--file solo se utiliza con send-invoice')
    sample = 'FACTURA F-2026-001\nProveedor: Taller Ejemplo SL\nTotal: 120,50 EUR\n'
    if args.file is not None:
        try:
            if args.file.suffix.lower() != '.txt' or args.file.stat().st_size > 65536:
                raise ValueError('Utiliza un TXT de hasta 64 KiB')
            sample = args.file.read_text(encoding='utf-8-sig')
            if not sample.strip() or len(sample) > 12000:
                raise ValueError('El TXT debe contener entre 1 y 12000 caracteres')
        except (OSError, UnicodeError, ValueError) as error:
            parser.error(str(error))
    namespace = os.getenv('SERVICEBUS_NAMESPACE', '')
    queue = os.getenv('SERVICEBUS_QUEUE', 'documentos')
    if not namespace.endswith('.servicebus.windows.net') or '/' in namespace or not queue:
        parser.error('Configura SERVICEBUS_NAMESPACE=<nombre>.servicebus.windows.net y SERVICEBUS_QUEUE')
    try:
        with AzureCliCredential() as credential:
            with ServiceBusClient(namespace, credential, retry_total=0,
                                  transport_type=TransportType.AmqpOverWebsocket) as client:
                if args.action in ('send', 'send-blob', 'send-invoice', 'resend-invoice'):
                    message_id = str(uuid4())
                    payload = dict(operation='analyze', document_id=str(uuid4()), simulated=True)
                    if args.action == 'resend-invoice':
                        payload.update(operation='extract_blob', document_id=str(args.document_id), simulated=False)
                        print(f'Reutilizando documento existente: {args.document_id}; no se sube otro archivo.')
                    if args.action in ('send-blob', 'send-invoice'):
                        from azure.storage.blob import BlobServiceClient
                        account_url = 'https://stai200373840.blob.core.windows.net'
                        blob_name = f"servicebus-lab/{payload['document_id']}.txt"
                        with BlobServiceClient(account_url, credential=credential) as storage:
                            storage.get_blob_client('documents', blob_name).upload_blob(sample.encode('utf-8'), overwrite=False)
                        payload.update(operation='extract_blob' if args.action == 'send-invoice' else 'analyze_blob', simulated=False)
                        print(f'Archivo subido: documents/{blob_name}')
                        if args.action == 'send-invoice':
                            print(f'Resultado esperado: documents/servicebus-results/{payload["document_id"]}.json')
                    with client.get_queue_sender(queue) as sender:
                        sender.send_messages(ServiceBusMessage(json.dumps(payload),
                                             content_type='application/json', message_id=message_id))
                    print(f'Enviado: {message_id}. Operación: {payload["operation"]}')
                    return
                options = dict(queue_name=queue, receive_mode=ServiceBusReceiveMode.PEEK_LOCK,
                               prefetch_count=0, max_wait_time=5)
                if args.action in ('dlq', 'replay'):
                    options['sub_queue'] = ServiceBusSubQueue.DEAD_LETTER
                with client.get_queue_receiver(**options) as receiver:
                    if args.action in ('peek', 'dlq'):
                        messages = receiver.peek_messages(max_message_count=10, timeout=15)
                    else:
                        messages = receiver.receive_messages(max_message_count=1, max_wait_time=5)
                    if not messages:
                        print('No se han encontrado mensajes en esta consulta.')
                    for message in messages:
                        print(f'ID={message.message_id} delivery_count={message.delivery_count}')
                        print(str(message))
                        if args.action == 'renew':
                            initial = message.locked_until_utc
                            if initial is None:
                                raise ValueError('El mensaje no tiene bloqueo PeekLock')
                            remaining = (initial - datetime.now(timezone.utc)).total_seconds()
                            print(f'Bloqueo inicial hasta {initial.isoformat()}. Renovaremos a mitad del plazo.', flush=True)
                            time.sleep(max(0, remaining / 2))
                            renewed = receiver.renew_message_lock(message)
                            print(f'Bloqueo renovado hasta {renewed.isoformat()}. Continuamos trabajando...', flush=True)
                            # Terminar después del plazo original, dentro del nuevo bloqueo.
                            wait = max(0, (initial - datetime.now(timezone.utc)).total_seconds()) + 2
                            if (renewed - datetime.now(timezone.utc)).total_seconds() <= wait + 2:
                                receiver.abandon_message(message)
                                print('Margen insuficiente para la demostración; mensaje abandonado. Comprueba el reloj y LockDuration.')
                                continue
                            time.sleep(wait)
                            receiver.complete_message(message)
                            print('Complete correcto después del plazo original: la renovación conservó el bloqueo.')
                        elif args.action == 'expire':
                            until = message.locked_until_utc
                            if until is None:
                                raise ValueError('El mensaje no tiene bloqueo PeekLock')
                            seconds = max(0, (until - datetime.now(timezone.utc)).total_seconds()) + 3
                            print(f'Bloqueado hasta {until.isoformat()}. Esperando {seconds:.0f}s sin renovar ni confirmar...', flush=True)
                            time.sleep(seconds)
                            try:
                                receiver.complete_message(message)
                            except MessageLockLostError:
                                print('MessageLockLostError esperado: ya no puedes confirmar con el bloqueo anterior.')
                                print('Ejecuta receive para observar la nueva entrega y confirmarla.')
                            else:
                                print('Complete aceptado: no se observó la caducidad esperada; revisa tiempos y configuración.')
                        elif args.action == 'replay':
                            replay_message(client, queue, receiver, message)
                            print('Reenviado a la cola principal y original confirmado en DLQ.')
                            print('Envío y confirmación no son atómicos: un fallo intermedio puede duplicar el mensaje.')
                        elif args.action == 'receive':
                            # Procesamiento didáctico: observar el mensaje y confirmar.
                            receiver.complete_message(message)
                            print('Complete: mensaje retirado de la cola.')
                        elif args.action == 'fail':
                            receiver.abandon_message(message)
                            print('Abandon: fallo simulado; Azure podrá entregarlo otra vez.')
                        elif args.action == 'dlq':
                            print(f'Motivo={message.dead_letter_reason}; descripción={message.dead_letter_error_description}')
                        else:
                            print('Peek: consulta sin bloquear ni retirar el mensaje.')
    except AzureError as error:
        parser.exit(1, f'Error de Azure ({type(error).__name__}): {error}\n')


if __name__ == '__main__':
    main()
