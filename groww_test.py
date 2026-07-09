import os
from growwapi import GrowwAPI

token = os.getenv("GROWW_ACCESS_TOKEN")

print("Token present:", bool(token))

groww = GrowwAPI(token)

print("HOLDINGS:")
print(groww.get_holdings_for_user(timeout=10))

print("POSITIONS:")
print(groww.get_positions_for_user(segment=groww.SEGMENT_CASH))
