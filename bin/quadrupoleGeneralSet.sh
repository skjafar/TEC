#!/usr/bin/bash

for cell in {01..16}
do
    for number in {1..2}
    do
    caput SRC$cell-PS-$1$number:$2 $3
    done
done