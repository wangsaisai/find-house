#!/bin/bash

# The endpoint to test
URL="http://127.0.0.1:8000/find_rental_location"

# The JSON payload with two addresses
JSON_PAYLOAD='{
  "address1": "浦东外高桥",
  "address2": "德国中心"
}'

# Execute the curl command
curl -X POST "$URL" \
     -H "Content-Type: application/json" \
     -d "$JSON_PAYLOAD"

echo # Add a newline for better formatting
