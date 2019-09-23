import os, uuid, sys
import json
import argparse
from azure.storage.blob import BlockBlobService, PublicAccess


# Get input arguments
parser = argparse.ArgumentParser(description='Get the latest flow logs in a storage account')
parser.add_argument('--accountName', dest='accountName', action='store',
                    help='you need to supply an storage account name. You can get a list of your storage accounts with this command: az storage account list -o table')
parser.add_argument('--displayLB', dest='displayLB', action='store_true',
                    default=False,
                    help='display or hide flows generated by the Azure LB (default: False)')
parser.add_argument('--displayAllowed', dest='displayAllowed', action='store_true',
                    default=False,
                    help='display as well flows allowed by NSGs (default: False)')
parser.add_argument('--displayDirection', dest='displayDirection', action='store', default='in',
                    help='display flows only in a specific direction. Can be in, out, or both (default in)')
parser.add_argument('--displayHours', dest='displayHours', action='store', type=int, default=1,
                    help='How many hours to look back (default: 1)')
parser.add_argument('--verbose', dest='verbose', action='store_true',
                    default=False,
                    help='run in verbose mode (default: False)')
args = parser.parse_args()

# Setting storage account name and key
accountName = args.accountName
try:
    accountKey = os.environ.get('STORAGE_ACCOUNT_KEY')
except:
    print('The environment variable STORAGE_ACCOUNT_KEY does not exist. You can create it with this command: export STORAGE_ACCOUNT_KEY=$(az storage account keys list -n your_storage_account_name --query [0].value -o tsv)')
    exit(1)
if accountKey == None:
    print('The environment variable STORAGE_ACCOUNT_KEY does not exist. You can create it with this command: export STORAGE_ACCOUNT_KEY=$(az storage account keys list -n your_storage_account_name --query [0].value -o tsv)')
    exit(1)
if args.verbose:
    print('DEBUG: Storage account:', accountName)

# This name should be the same for all blobs for NSG flows 
containerName = "insights-logs-networksecuritygroupflowevent"

# Set to true if only packet drops should be displayed
displayOnlyDrops = not args.displayAllowed

# Set to "in", "out" or "both"
displayDirection = args.displayDirection
if not displayDirection in set(['in', 'out', 'both']):
    print('Please see this script help about how to set the displayDirection argument')

# Set to False if you dont want to see traffic generated by the Azure Load Balancer
displayLB = args.displayLB

# How many blobs to inspect (in an ordered list, there is one blob per minute)
displayHours = args.displayHours

block_blob_service = BlockBlobService(account_name=accountName, account_key=accountKey)
blobList = block_blob_service.list_blobs(containerName)

if args.verbose:
    print('DEBUG: Display variables: displayLB:', displayLB, '- displayDirection:', displayDirection, '- displayHours:', displayHours, '- displayOnlyDrops:', displayOnlyDrops)

# Get a list of NSGs
# List comprehension does not seem to work (TypeError: 'ListGenerator' object is not subscriptable)
# nsgList = [blobList[i].name.split('/')[8] for i in blobList]
nsgList = set([])
for thisBlob in blobList:
    blobNameParts = thisBlob.name.split('/')
    thisNsg = blobNameParts[8]
    if not thisNsg in nsgList:
        nsgList.add(thisNsg)
if args.verbose:
    print('DEBUG: NSGs found in that storage account:', nsgList)

for nsgName in nsgList:
    # Get a list of days for a given NSG
    # List comprehensions do not seem to work (TypeError: 'ListGenerator' object is not subscriptable)
    # dayList = [blobList[i].split('/')[11] for i in blobList if blobList[i].split('/')[8] == nsgName]
    dateList = []
    for thisBlob in blobList:
        blobNameParts = thisBlob.name.split('/')
        blobNsg  = blobNameParts[8]
        blobTime = "/".join(blobNameParts[9:14])
        if blobNsg == nsgName:
            dateList.append(blobTime)
    dateList = sorted(dateList, reverse=True)
    dateList = dateList[:displayHours]
    if args.verbose:
        print('DEBUG: Hourly blobs found for NSG', nsgName, ':', dateList, '- displayHours: ', displayHours)

    for thisDate in dateList:
        # Get the corresponding blob for a given NSG and date
        blobMatches = []
        for thisBlob in blobList:
            blobNameParts = thisBlob.name.split('/')
            blobNsg  = blobNameParts[8]
            blobTime = "/".join(blobNameParts[9:14])
            if blobNsg == nsgName and blobTime == thisDate:
                blobMatches.append(thisBlob.name)

        for blobName in blobMatches:
            if args.verbose:
                print('DEBUG: Reading blob', blobName)
            localFilename = "flowlog_tmp.json"
            if os.path.exists(localFilename):
                os.remove(localFilename)
            block_blob_service.get_blob_to_path(containerName, blobName, localFilename)
            textData=open(localFilename).read()
            data = json.loads(textData)
            for record in data['records']:
                for rule in record['properties']['flows']:
                    for flow in rule['flows']:
                        for flowtuple in flow['flowTuples']:
                            tupleValues = flowtuple.split(',')
                            srcIp=tupleValues[1]
                            dstIp=tupleValues[2]
                            srcPort=tupleValues[3]
                            dstPort=tupleValues[4]
                            direction=tupleValues[6]
                            action=tupleValues[7]
                            displayRecord = False
                            if action=='D' or not displayOnlyDrops:
                                if (direction == 'I' and displayDirection == 'in') or (direction == 'O' and displayDirection == 'out') or (displayDirection == 'both'):
                                        if srcIp != "168.63.129.16" or displayLB == True:
                                            displayRecord = True
                            if displayRecord:
                                print(record['time'], nsgName, rule['rule'], action, direction, srcIp, srcPort, dstIp, dstPort)
