from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import DocumentField
# from azure.ai.documentintelligence import DocumentIntelligenceClient
from common.config import settings, logger
from pathlib import Path


# ── Load configuration from environment 
AZ_ENDPOINT = settings.AZURE_AI_DOCUMENT_INTELLIGENCE_ENDPOINT
AZ_KEY = settings.AZURE_AI_DOCUMENT_INTELLIGENCE_KEY
MODEL_ID = settings.AZURE_CUSTOM_MODEL_ID


if not (AZ_ENDPOINT and AZ_KEY):
    raise RuntimeError("Please set AZURE_AI_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_AI_DOCUMENT_INTELLIGENCE_KEY")


# ── Azure client 
client = DocumentIntelligenceClient(
    endpoint=AZ_ENDPOINT,
    credential=AzureKeyCredential(AZ_KEY)
)


def extract_value(field: DocumentField):
    if field.type == "array" and field.value_array:
        return [extract_value(item) for item in field.value_array]
    if field.type == "object" and field.value_object:
        return {k: extract_value(v) for k, v in field.value_object.items()}
    return (
        field.value_string        or field.value_number        or
        field.value_integer       or field.value_date          or
        field.value_time          or field.value_phone_number  or
        field.value_boolean       or field.value_currency      or
        field.value_country_region or field.value_address      or
        field.value_selection_mark or field.value_signature    or
        field.value_selection_group or field.content
    )


async def analyze_report(file_path: str):
    try:
        file_path = Path(file_path)

        async with DocumentIntelligenceClient(endpoint=AZ_ENDPOINT, credential=AzureKeyCredential(AZ_KEY)) as client:
            try:
                with open(file_path, "rb") as f:
                    poller = await client.begin_analyze_document(MODEL_ID, f)
                    result = await poller.result()
            except Exception as e:
                logger.error(f"Azure Document Intelligence error: {e}")
                raise Exception(f"Azure Document Intelligence error: {e}")

        if not result.documents:
            raise Exception("No document fields found")

        doc = result.documents[0]
        clean_fields = {name: extract_value(f) for name, f in doc.fields.items()}

        return clean_fields
    except Exception as e:
        logger.error(f"Azure Document Intelligence error: {e}")
        raise Exception(f"Azure Document Intelligence error: {e}")


