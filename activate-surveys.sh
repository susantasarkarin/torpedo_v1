#!/bin/bash

# Activate CPX surveys for US
echo "Activating CPX surveys for US..."
mongosh localhost:27017/cpx_research --eval 'db.cpx_surveys.updateMany({country: "US"}, {$set: {is_active_in_pool: true}})'

# Activate all CINT surveys
echo "Activating all CINT surveys..."
mongosh localhost:27017/cint_research --eval 'db.cint_surveys.updateMany({}, {$set: {is_active_in_pool: true}})'

# Check counts
echo "Checking active survey counts..."
mongosh localhost:27017/cpx_research --eval 'print("CPX US Active:", db.cpx_surveys.countDocuments({is_active_in_pool: true, country: "US"})); print("CPX Total:", db.cpx_surveys.countDocuments({}))'
mongosh localhost:27017/cint_research --eval 'print("CINT Active:", db.cint_surveys.countDocuments({is_active_in_pool: true})); print("CINT Total:", db.cint_surveys.countDocuments({}))'

echo "Done!"
