#!/usr/bin/bash

caput SR-PS-BM:$1 $2
./quadrupoleGeneralSet.sh QF $1 $2
./quadrupoleGeneralSet.sh QD $1 $2
./sextupoleGeneralSet.sh SF $1 $2
./sextupoleGeneralSet.sh SD $1 $2
