# from Crypto.Cipher import AES
# from Crypto.Random import get_random_bytes
# import base64

# def encrypt_file(file_bytes: bytes, key: bytes):
#     cipher = AES.new(key, AES.MODE_GCM)
#     ciphertext, tag = cipher.encrypt_and_digest(file_bytes)
#     return cipher.nonce + tag + ciphertext  # prepend nonce and tag



# def decrypt_file(encrypted_data: bytes, key: bytes):
#     nonce = encrypted_data[:16]
#     tag = encrypted_data[16:32]
#     ciphertext = encrypted_data[32:]
#     cipher = AES.new(key, AES.MODE_GCM, nonce)
#     return cipher.decrypt_and_verify(ciphertext, tag)



    