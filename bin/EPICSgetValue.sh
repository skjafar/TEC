
for x in $(jot $2 2>/dev/null || seq $2); do
    VAL="$(caget $1)"
    #echo $VAL
    VAL=${VAL##* }
    echo $VAL
    sleep $3
done
killall -s SIGINT diagram 
