"""Práctica independiente con una cola real de Azure Service Bus."""
import argparse
import json
import os
from uuid import uuid4

from azure.identity import AzureCliCredential
from azure.servicebus import (ServiceBusClient, ServiceBusMessage, ServiceBusReceiveMode,
                              ServiceBusSubQueue, TransportType)
from azure.core.exceptions import AzureError


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
    parser.add_argument('action', choices=['send', 'receive', 'fail', 'peek', 'dlq', 'replay'])
    args = parser.parse_args()
    namespace = os.getenv('SERVICEBUS_NAMESPACE', '')
    queue = os.getenv('SERVICEBUS_QUEUE', 'documentos')
    if not namespace.endswith('.servicebus.windows.net') or '/' in namespace or not queue:
        parser.error('Configura SERVICEBUS_NAMESPACE=<nombre>.servicebus.windows.net y SERVICEBUS_QUEUE')
    try:
        with AzureCliCredential() as credential:
            with ServiceBusClient(namespace, credential, retry_total=0,
                                  transport_type=TransportType.AmqpOverWebsocket) as client:
                if args.action == 'send':
                    message_id = str(uuid4())
                    payload = dict(operation='analyze', document_id=str(uuid4()), simulated=True)
                    with client.get_queue_sender(queue) as sender:
                        sender.send_messages(ServiceBusMessage(json.dumps(payload),
                                             content_type='application/json', message_id=message_id))
                    print(f'Enviado: {message_id}. El document_id es ficticio; no se analiza ningún archivo.')
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
                        if args.action == 'replay':
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
