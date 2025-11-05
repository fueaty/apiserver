#!/usr/bin/env python3
"""
用于加密和解密敏感凭证文件的简单脚本
"""

import os
import sys
from cryptography.fernet import Fernet

def generate_key():
    """生成加密密钥"""
    key = Fernet.generate_key()
    with open("secret/.encryption_key", "wb") as key_file:
        key_file.write(key)
    print("密钥已生成并保存到 secret/.encryption_key")

def load_key():
    """加载加密密钥"""
    return open("secret/.encryption_key", "rb").read()

def encrypt_file(filename):
    """加密文件"""
    key = load_key()
    f = Fernet(key)
    
    with open(filename, "rb") as file:
        file_data = file.read()
    
    encrypted_data = f.encrypt(file_data)
    
    with open(filename + ".encrypted", "wb") as file:
        file.write(encrypted_data)
    
    print(f"文件 {filename} 已加密为 {filename}.encrypted")

def decrypt_file(filename):
    """解密文件"""
    key = load_key()
    f = Fernet(key)
    
    with open(filename, "rb") as file:
        encrypted_data = file.read()
    
    decrypted_data = f.decrypt(encrypted_data)
    
    with open(filename.replace(".encrypted", ""), "wb") as file:
        file.write(decrypted_data)
    
    print(f"文件 {filename} 已解密")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法:")
        print("  python encrypt_credentials.py generate_key")
        print("  python encrypt_credentials.py encrypt <filename>")
        print("  python encrypt_credentials.py decrypt <filename.encrypted>")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "generate_key":
        generate_key()
    elif command == "encrypt":
        encrypt_file(sys.argv[2])
    elif command == "decrypt":
        decrypt_file(sys.argv[2])
    else:
        print("未知命令")
        sys.exit(1)