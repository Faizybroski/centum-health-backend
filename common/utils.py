
from azure.storage.blob import BlobServiceClient, ContentSettings
from fastapi import UploadFile
from common.config import settings


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def upload_to_azure_blob(file: UploadFile, container_name: str, blob_name: str) -> str:
    account_url = settings.AZURE_STORAGE_ACCOUNT_URL
    account_key = settings.AZURE_STORAGE_ACCOUNT_KEY

    if not account_url or not account_key:
        raise ValueError("Azure Storage account URL or key not set.")

    blob_service_client = BlobServiceClient(account_url=account_url, credential=account_key)
    container_client = blob_service_client.get_container_client(container_name)

    try:
        container_client.create_container()
    except Exception:
        pass  # assume exists

    blob_client = container_client.get_blob_client(blob_name)

    content_settings = ContentSettings(content_type=file.content_type)

    file.file.seek(0)
    blob_client.upload_blob(file.file, overwrite=True, content_settings=content_settings)

    return blob_client.url


# async def upload_to_azure_blob(file: UploadFile, container_name: str, blob_name: str, encryption_key: bytes) -> str:
#     account_url = settings.AZURE_STORAGE_ACCOUNT_URL
#     account_key = settings.AZURE_STORAGE_ACCOUNT_KEY

#     if not account_url or not account_key:
#         raise ValueError("Azure Storage account URL or key not set.")

#     blob_service_client = BlobServiceClient(account_url=account_url, credential=account_key)
#     container_client = blob_service_client.get_container_client(container_name)

#     try:
#         container_client.create_container()
#     except Exception:
#         pass  # assume container exists

#     blob_client = container_client.get_blob_client(blob_name)

#     # Read and encrypt file
#     file.file.seek(0)
#     file_bytes = await file.read()
#     encrypted_data = encrypt_file(file_bytes, encryption_key)

#     encrypted_stream = io.BytesIO(encrypted_data)

#     content_settings = ContentSettings(content_type="application/octet-stream")  # encrypted file, not original type

#     blob_client.upload_blob(encrypted_stream, overwrite=True, content_settings=content_settings)

#     return




# def decrypt_data_aes(encrypted_data: bytes, key: bytes, iv: bytes) -> bytes:
#     cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
#     decryptor = cipher.decryptor()
#     decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

#     # Remove padding (PKCS7)
#     padding_length = decrypted[-1]
#     return decrypted[:-padding_length]



