
import sys
sys.path.append('/home/power/UserWorkspace/PowerSupplies/Python_testing_grounds/TEC')
import epicstest
import yaml

inputFile = open("test.yaml", 'r')
data = yaml.load(inputFile)
#print(data)
