#!/usr/local/bin/python3

import argparse
import yaml
import copy

parser = argparse.ArgumentParser()
parser.add_argument('-tf', help='YAML file with a list of device names to be substituted in the template file')
parser.add_argument('-af', help='YAML file with a list of device names to be substituted in the template file')
parser.add_argument('-of', '--OutputFile', help='YAML file that will be placed just after the repeated content')
parser.add_argument('-hf', '--HeaderFile', help='YAML file that will be placed just before the repeated content')
parser.add_argument('-ff', '--FooterFile', help='YAML file that will be placed just after the repeated content')


def main():
    args = parser.parse_args()
    aliasFile = open(args.af, 'r')
    aliases = yaml.load(aliasFile)
    aliasFile.close()
    
    templateFile = open(args.tf, 'r')
    templateConfig = yaml.load(templateFile)
    templateFile.close()
    
    if args.HeaderFile:
        headerFile = open(args.HeaderFile, 'r')
        header = yaml.load(headerFile)
        headerFile.close()
    else:
        header = []

    if args.FooterFile:
        footerFile = open(args.FooterFile, 'r')
        footer = yaml.load(footerFile)
        footerFile.close()
    else:
        footer = []

    combinedoutput = []

    for alias in aliases:
        newRow = copy.deepcopy(templateConfig)
        for row in newRow:
            for field in row:
                if "device_name" in field:
                    if field['device_name'] == 'PS1':
                        field['device_name'] = alias[0]
                    elif field['device_name'] == 'PS2':
                        field['device_name'] = alias[1]

                if "markup" in field:
                    if field['markup'] == 'PS1':
                        field['markup'] = alias[0]
                    elif field['markup'] == 'PS2':
                        field['markup'] = alias[1]

        combinedoutput = combinedoutput + copy.deepcopy(newRow)
        #combinedoutput.append(copy.deepcopy(templateConfig))

    if args.OutputFile:
        outputFile = open(args.of, 'w')
        yaml.dump(header + combinedoutput + footer, outputFile)
        outputFile.close()
    else:
        print(yaml.dump(header + combinedoutput + footer))


    #columns_list = []
    #for PV in testPVfromConfig:
    #    columns_list.append(('fixed', 10, PV))




if __name__ == '__main__':
    main()
