#!/bin/bash

export DB_CLIENT_ID="..."
export DB_CLIENT_SECRET="..."

export KEEP_MINUTES=30

export DB_STATION="8004128" # Donnersbergerbrücke
#export DB_STATION="8011160" # Berlin Hbf

python3.10 main.py
