#!/bin/bash

EPICSgetValue.sh $1 $2 0.5 | diagram.py -b &
PID=$!
while read -n 1 -s key
do
  if [ $key = q ]
  then

    kill -KILL ${PID}
    break
  fi
done 
kill -KILL ${PID}
