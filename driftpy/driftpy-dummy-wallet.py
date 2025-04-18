# the goal of this script is to connect to create a dummy keypair for connecting to driftpy

import os
import asyncio
from anchorpy import Wallet
from dotenv import load_dotenv
from driftpy.keypair import load_keypair
from driftpy.drift_client import DriftClient
from driftpy.user_map.user_map import UserMap
from driftpy.user_map.user_map_config import UserMapConfig, PollingConfig
from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair # type: ignore
import base58

load_dotenv()  # load environment variables from .env file

# Generate a random Solana keypair (wallet) for interaction with Drift
kp = Keypair()

# create a wallet from the keypair
wallet = Wallet(kp)

public_key = kp.pubkey()
private_key = kp.secret()
print(f"Private Key: {private_key}")

# Combine private and public key for full keypair
full_key = private_key + bytes(public_key)

# Encode the full keypair in base58
keypair_base58 = base58.b58encode(full_key).decode('utf-8')

print(f"Public Key: {public_key}")
print(f"Private Key (base58): {keypair_base58}")