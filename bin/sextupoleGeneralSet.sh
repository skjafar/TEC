#!/usr/bin/bash

for number in {1..2}
do
    caput SR-PS-$1$number:$2 $3
done
