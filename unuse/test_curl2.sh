#!/bin/bash

# The endpoint to test
URL="http://127.0.0.1:8000/find_rental_location"

# The JSON payload with two work addresses
JSON_PAYLOAD='{
  "work_address1": "浦东外高桥",
  "work_address2": "德国中心",
  "budget_range": "5000-8000元",
  "preferences": "靠近地铁，环境安静"
}'

# Execute the curl command
curl -X POST "$URL" \
     -H "Content-Type: application/json" \
     -d "$JSON_PAYLOAD"

echo # Add a newline for better formatting
