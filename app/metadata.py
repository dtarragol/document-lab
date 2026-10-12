"""Repositorios de metadatos intercambiables. Los originales siguen en Blob Storage."""
import json

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings


class BlobMetadata:
    def __init__(self, container):
        self.container = container

    def check(self):
        self.container.get_container_properties()

    def _read(self, name):
        return json.loads(self.container.get_blob_client(name).download_blob().readall())

    def _create(self, name, value):
        self.container.get_blob_client(name).upload_blob(json.dumps(value).encode(), overwrite=False,
            content_settings=ContentSettings(content_type="application/json"))

    def create(self, item):
        self._create(f"metadata/{item['id']}.json", item)

    def get(self, document_id):
        item = self._read(f"metadata/{document_id}.json")
        try:
            item["analysis"] = self._read(f"results/{document_id}.json")
            item["status"] = "Analyzed"
        except ResourceNotFoundError:
            pass
        return item

    def save_analysis(self, document_id, result):
        try:
            self._create(f"results/{document_id}.json", result)
        except ResourceExistsError:
            pass
        return self.get(document_id)


class CosmosMetadata:
    def __init__(self, container):
        self.container = container

    def check(self):
        properties = self.container.read()
        if properties.get("partitionKey", {}).get("paths") != ["/id"]:
            raise RuntimeError("El contenedor Cosmos debe utilizar la clave de partición /id")

    def create(self, item):
        self.container.create_item(body=item)

    def get(self, document_id):
        # Lectura puntual: ID + valor de partición, sin consulta entre particiones.
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        try:
            return self.container.read_item(item=str(document_id), partition_key=str(document_id))
        except CosmosResourceNotFoundError as error:
            raise ResourceNotFoundError("Documento no encontrado") from error

    def save_analysis(self, document_id, result):
        from azure.cosmos.exceptions import CosmosHttpResponseError
        item = self.get(document_id)
        if item.get("analysis") is not None:
            return item
        etag = item["_etag"]
        updated = {key: value for key, value in item.items() if not key.startswith("_")}
        updated.update(analysis=result, status="Analyzed")
        try:
            return self.container.replace_item(item=str(document_id), body=updated,
                etag=etag, match_condition=MatchConditions.IfNotModified)
        except CosmosHttpResponseError as error:
            if error.status_code != 412:
                raise
            winner = self.get(document_id)
            if winner.get("analysis") is None:
                raise
            return winner
