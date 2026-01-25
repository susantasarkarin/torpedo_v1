#!/bin/bash

# Activate ALL CPX surveys (no country filter - CPX handles routing)
echo "Activating ALL CPX surveys..."
mongosh localhost:27017/cpx_research --eval 'db.cpx_surveys.updateMany({}, {$set: {is_active_in_pool: true}})'

# Check counts
echo "Checking CPX survey counts..."
mongosh localhost:27017/cpx_research --eval 'print("CPX Active:", db.cpx_surveys.countDocuments({is_active_in_pool: true})); print("CPX Total:", db.cpx_surveys.countDocuments({}))'

echo "Done!"
