#!/usr/bin/env python
# Copyright 2010, Jeremy Collins
# Distribute under the terms of the GNU General Public License
# Version 2 or better
#
#Originally Based on miranda-upnp:
################################
# miranda-upnp                 #
# Interactive UPNP application #
# Craig Heffner                #
# www.sourcesec.com            #
# 07/16/2008                   #
# Released under a MIT License #
################################



upnp_server_list = {}



try:
    import sys,os
    from socket import *
    from urllib2 import URLError, HTTPError
    from platform import system as thisSystem
    import xml.dom.minidom as minidom
    import urllib,urllib2
    import time
    import pickle
    import struct
    import base64
    import re
    import getopt
    import logging
    import datetime

except Exception,e:
    logging.debug( 'Unmet dependency:',e)
    sys.exit(1)

#UPNP class for getting, sending and parsing SSDP/SOAP XML data (among other things...)
class upnp:
    ip = False
    port = False
    completer = False
    msearchHeaders = {
        'MAN' : '"ssdp:discover"',
        'MX'  : '2'
    }
    DEFAULT_IP = "239.255.255.250"
    DEFAULT_PORT = 1900
    UPNP_VERSION = '1.0'
    MAX_RECV = 8192
    HTTP_HEADERS = []
    ENUM_HOSTS = {}
    VERBOSE = False
    UNIQ = False
    DEBUG = False
    LOG_FILE = False
    IFACE = None
    STARS = '****************************************************************'
    csock = False
    ssock = False

    def __init__(self,ip,port,iface):
        if self.initSockets(ip,port,iface) == False:
            logging.debug('UPNP class initialization failed!')
            logging.debug( 'Bye!')
            sys.exit(1)
        else:
            self.soapEnd = re.compile('<\/.*:envelope>')

    #Initialize default sockets
    def initSockets(self,ip,port,iface):
        if self.csock:
            self.csock.close()
        if self.ssock:
            self.ssock.close()

        if iface != None:
            self.IFACE = iface
        if not ip:
            ip = self.DEFAULT_IP
        if not port:
            port = self.DEFAULT_PORT
        self.port = port
        self.ip = ip

        try:
            #This is needed to join a multicast group
            self.mreq = struct.pack("4sl",inet_aton(ip),INADDR_ANY)

            #Set up client socket
            self.csock = socket(AF_INET,SOCK_DGRAM)
            self.csock.setsockopt(IPPROTO_IP,IP_MULTICAST_TTL,2)

            #Set up server socket
            self.ssock = socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP)
            self.ssock.setsockopt(SOL_SOCKET,SO_REUSEADDR,1)

            #Only bind to this interface
            if self.IFACE != None:
                logging.debug( '\nBinding to interface',self.IFACE,'...\n')
                self.ssock.setsockopt(SOL_SOCKET,IN.SO_BINDTODEVICE,struct.pack("%ds" % (len(self.IFACE)+1,), self.IFACE))
                self.csock.setsockopt(SOL_SOCKET,IN.SO_BINDTODEVICE,struct.pack("%ds" % (len(self.IFACE)+1,), self.IFACE))

            try:
                self.ssock.bind(('',self.port))
            except Exception, e:
                logging.debug( "WARNING: Failed to bind %s:%d: %s" , (self.ip,self.port,e))
            try:
                self.ssock.setsockopt(IPPROTO_IP,IP_ADD_MEMBERSHIP,self.mreq)
            except Exception, e:
                logging.debug( 'WARNING: Failed to join multicast group:',e)
        except Exception, e:
            logging.debug( "Failed to initialize UPNP sockets:",e)
            return False
        return True

    #Clean up file/socket descriptors
    def cleanup(self):
        if self.LOG_FILE != False:
            self.LOG_FILE.close()
        self.csock.close()
        self.ssock.close()

    #Send network data
    def send(self,data,socket):
        #By default, use the client socket that's part of this class
        if socket == False:
            socket = self.csock
        try:
            socket.sendto(data,(self.ip,self.port))
            return True
        except Exception, e:
            logging.debug( "SendTo method failed for %s:%d : %s" % (self.ip,self.port,e))
            return False

    #Listen for network data
    def listen(self,size,socket):
        if socket == False:
            socket = self.ssock

        try:
            return socket.recv(size)
        except:
            return False

    #Create new UDP socket on ip, bound to port
    def createNewListener(self,ip,port):
        try:
            newsock = socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP)
            newsock.setsockopt(SOL_SOCKET,SO_REUSEADDR,1)
            newsock.bind((ip,port))
            return newsock
        except:
            return False

    #Return the class's primary server socket
    def listener(self):
        return self.ssock

    #Return the class's primary client socket
    def sender(self):
        return self.csock

    #Parse a URL, return the host and the page
    def parseURL(self,url):
        delim = '://'
        host = False
        page = False

        #Split the host and page
        try:
            (host,page) = url.split(delim)[1].split('/',1)
            page = '/' + page
        except:
            #If '://' is not in the url, then it's not a full URL, so assume that it's just a relative path
            page = url

        return (host,page)

    #Pull the name of the device type from a device type string
    #The device type string looks like: 'urn:schemas-upnp-org:device:WANDevice:1'
    def parseDeviceTypeName(self,string):
        delim1 = 'device:'
        delim2 = ':'

        if delim1 in string and not string.endswith(delim1):
            return string.split(delim1)[1].split(delim2,1)[0]
        return False

    #Pull the name of the service type from a service type string
    #The service type string looks like: 'urn:schemas-upnp-org:service:Layer3Forwarding:1'
    def parseServiceTypeName(self,string):
        delim1 = 'service:'
        delim2 = ':'

        if delim1 in string and not string.endswith(delim1):
            return string.split(delim1)[1].split(delim2,1)[0]
        return False

    #Pull the header info for the specified HTTP header - case insensitive
    def parseHeader(self,data,header):
        delimiter = "%s:" % header
        defaultRet = False

        lowerDelim = delimiter.lower()
        dataArray = data.split("\r\n")

        #Loop through each line of the headers
        for line in dataArray:
            lowerLine = line.lower()
            #Does this line start with the header we're looking for?
            if lowerLine.startswith(lowerDelim):
                try:
                    return line.split(':',1)[1].strip()
                except:
                    logging.debug( "Failure parsing header data for %s" % header)
        return defaultRet

    #Extract the contents of a single XML tag from the data
    def extractSingleTag(self,data,tag):
        startTag = "<%s" % tag
        endTag = "</%s>" % tag

        try:
            tmp = data.split(startTag)[1]
            index = tmp.find('>')
            if index != -1:
                index += 1
                return tmp[index:].split(endTag)[0].strip()
        except:
            pass
        return None

    #Parses SSDP notify and reply packets, and populates the ENUM_HOSTS dict
    def parseSSDPInfo(self,data,showUniq,verbose):
        hostFound = False
        foundLocation = False
        messageType = False
        xmlFile = False
        host = False
        page = False
        upnpType = None
        knownHeaders = {
                'NOTIFY' : 'notification',
                'HTTP/1.1 200 OK' : 'reply'
        }

        #Use the class defaults if these aren't specified
        if showUniq == False:
            showUniq = self.UNIQ
        if verbose == False:
            verbose = self.VERBOSE

        #Is the SSDP packet a notification, a reply, or neither?
        for text,messageType in knownHeaders.iteritems():
            if data.upper().startswith(text):
                break
            else:
                messageType = False

        #If this is a notification or a reply message...
        if messageType != False:
            #Get the host name and location of it's main UPNP XML file
            xmlFile = self.parseHeader(data,"LOCATION")
            upnpType = self.parseHeader(data,"SERVER")
            (host,page) = self.parseURL(xmlFile)

            #Sanity check to make sure we got all the info we need
            if xmlFile == False or host == False or page == False:
                logging.debug( 'ERROR parsing recieved header:')
                logging.debug( self.STARS)
                logging.debug( data)
                logging.debug( self.STARS)
                logging.debug( '')
                return False

            #Get the protocol in use (i.e., http, https, etc)
            protocol = xmlFile.split('://')[0]+'://'

            #Check if we've seen this host before; add to the list of hosts if:
            #   1. This is a new host
            #   2. We've already seen this host, but the uniq hosts setting is disabled
            for hostID,hostInfo in self.ENUM_HOSTS.iteritems():
                if hostInfo['name'] == host:
                    hostFound = True
                    if self.UNIQ:
                        return False

            if (hostFound and not self.UNIQ) or not hostFound:
                #Get the new host's index number and create an entry in ENUM_HOSTS
                index = len(self.ENUM_HOSTS)
                self.ENUM_HOSTS[index] = {
                                'name' : host,
                                'dataComplete' : False,
                                'proto' : protocol,
                                'xmlFile' : xmlFile,
                                'serverType' : None,
                                'upnpServer' : upnpType,
                                'deviceList' : {}
                            }

            #Print out some basic device info
            logging.debug( self.STARS)
            logging.debug( "SSDP %s message from %s" % (messageType,host))

            if xmlFile:
                foundLocation = True
                logging.debug( "XML file is located at %s" % xmlFile)

            if upnpType:
                logging.debug( "Device is running %s"% upnpType)

            logging.debug( self.STARS)
            logging.debug( '')

    #Send GET request for a UPNP XML file
    def getXML(self,url):

        headers = {
                            'USER-AGENT':'uPNP/'+self.UPNP_VERSION,
                            'CONTENT-TYPE':'text/xml; charset="utf-8"'
                }

        try:
    #Use urllib2 for the request, it's awesome
            req = urllib2.Request(url, None, headers)
            response = urllib2.urlopen(req)
            output = response.read()
            headers = response.info()
            return (headers,output)
        except Exception, e:
            logging.debug( "Request for '%s' failed: %s" % (url,e))
            return (False,False)

    #Send SOAP request
    def sendSOAP(self,hostName,serviceType,controlURL,actionName,actionArguments):
        argList = ''
        soapResponse = ''

        if '://' in controlURL:
            urlArray = controlURL.split('/',3)
            if len(urlArray) < 4:
                controlURL = '/'
            else:
                controlURL = '/' + urlArray[3]


        soapRequest = 'POST %s HTTP/1.1\r\n' % controlURL

        #Check if a port number was specified in the host name; default is port 80
        if ':' in hostName:
            hostNameArray = hostName.split(':')
            host = hostNameArray[0]
            try:
                port = int(hostNameArray[1])
            except:
                logging.debug( 'Invalid port specified for host connection:',hostName[1])
                return False
        else:
            host = hostName
            port = 80

        #Create a string containing all of the SOAP action's arguments and values
        for arg,(val,dt) in actionArguments.iteritems():
            argList += '<%s>%s</%s>' % (arg,val,arg)

        #Create the SOAP request
        soapBody =  '<?xml version="1.0"?>\n'\
                '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope" SOAP-ENV:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">\n'\
                '<SOAP-ENV:Body>\n'\
                '\t<m:%s xmlns:m="%s">\n'\
                '%s\n'\
                '\t</m:%s>\n'\
                '</SOAP-ENV:Body>\n'\
                '</SOAP-ENV:Envelope>' % (actionName,serviceType,argList,actionName)

        #Specify the headers to send with the request
        headers =   {
                'Host':hostName,
                'Content-Length':len(soapBody),
                'Content-Type':'text/xml',
                'SOAPAction':'"%s#%s"' % (serviceType,actionName)
                }

        #Generate the final payload
        for head,value in headers.iteritems():
            soapRequest += '%s: %s\r\n' % (head,value)
        soapRequest += '\r\n%s' % soapBody

        #Send data and go into recieve loop
        try:
            sock = socket(AF_INET,SOCK_STREAM)
            sock.connect((host,port))
            sock.send(soapRequest)
            while True:
                data = sock.recv(self.MAX_RECV)
                if not data:
                    break
                else:
                    soapResponse += data
                    if self.soapEnd.search(soapResponse.lower()) != None:
                        break
                        sock.close()

            (header,body) = soapResponse.split('\r\n\r\n',1)
            if not header.upper().startswith('HTTP/1.1 200'):
                logging.debug( 'SOAP request failed with error code:',header.split('\r\n')[0].split(' ',1)[1])
                errorMsg = self.extractSingleTag(body,'errorDescription')
                if errorMsg:
                    logging.debug( 'SOAP error message:',errorMsg)
                return False
            else:
                return body
        except Exception, e:
                logging.debug( 'Caught socket exception:',e)
                sock.close()
                return False
        except KeyboardInterrupt:
                sock.close()
                return False


    #Display all info for a given host
    def showCompleteHostInfo(self,index,fp):
        na = 'N/A'
        serviceKeys = ['controlURL','eventSubURL','serviceId','SCPDURL','fullName']
        if fp == False:
            fp = sys.stdout

        if index < 0 or index >= len(self.ENUM_HOSTS):
            fp.write('Specified host does not exist...\n')
            return
        try:
            hostInfo = self.ENUM_HOSTS[index]
            if hostInfo['dataComplete'] == False:
                logging.debug( "Cannot show all host info because we don't have it all yet. Try running 'host info %d' first...\n" % index)
            fp.write('Host name:         %s\n' % hostInfo['name'])
            fp.write('UPNP XML File:     %s\n\n' % hostInfo['xmlFile'])

            fp.write('\nDevice information:\n')
            for deviceName,deviceStruct in hostInfo['deviceList'].iteritems():
                fp.write('\tDevice Name: %s\n' % deviceName)
                for serviceName,serviceStruct in deviceStruct['services'].iteritems():
                    fp.write('\t\tService Name: %s\n' % serviceName)
                    for key in serviceKeys:
                        fp.write('\t\t\t%s: %s\n' % (key,serviceStruct[key]))
                    fp.write('\t\t\tServiceActions:\n')
                    for actionName,actionStruct in serviceStruct['actions'].iteritems():
                        fp.write('\t\t\t\t%s\n' % actionName)
                        for argName,argStruct in actionStruct['arguments'].iteritems():
                            fp.write('\t\t\t\t\t%s \n' % argName)
                            for key,val in argStruct.iteritems():
                                if key == 'relatedStateVariable':
                                    fp.write('\t\t\t\t\t\t%s:\n' % val)
                                    for k,v in serviceStruct['serviceStateVariables'][val].iteritems():
                                        fp.write('\t\t\t\t\t\t\t%s: %s\n' % (k,v))
                                else:
                                    fp.write('\t\t\t\t\t\t%s: %s\n' % (key,val))

        except Exception, e:
            logging.debug( 'Caught exception while showing host info:',e)

    #Wrapper function...
    def getHostInfo(self,xmlData,xmlHeaders,index):
        if self.ENUM_HOSTS[index]['dataComplete'] == True:
            return

        if index >= 0 and index < len(self.ENUM_HOSTS):
            try:
                xmlRoot = minidom.parseString(xmlData)
                self.parseDeviceInfo(xmlRoot,index)
                self.ENUM_HOSTS[index]['serverType'] = xmlHeaders.getheader('Server')
                self.ENUM_HOSTS[index]['dataComplete'] = True
                return True
            except Exception, e:
                logging.debug( 'Caught exception while getting host info:',e)
        return False

    #Parse device info from the retrieved XML file
    def parseDeviceInfo(self,xmlRoot,index):
        deviceEntryPointer = False
        devTag = "device"
        deviceType = "deviceType"
        deviceListEntries = "deviceList"
        deviceTags = ["friendlyName","modelDescription","modelName","modelNumber","modelURL","presentationURL","UDN","UPC","manufacturer","manufacturerURL"]

        #Find all device entries listed in the XML file
        for device in xmlRoot.getElementsByTagName(devTag):
            try:
                #Get the deviceType string
                deviceTypeName = str(device.getElementsByTagName(deviceType)[0].childNodes[0].data)
            except:
                continue

            #Pull out the action device name from the deviceType string
            deviceDisplayName = self.parseDeviceTypeName(deviceTypeName)
            if not deviceDisplayName:
                continue

            #Create a new device entry for this host in the ENUM_HOSTS structure
            deviceEntryPointer = self.ENUM_HOSTS[index][deviceListEntries][deviceDisplayName] = {}
            deviceEntryPointer['fullName'] = deviceTypeName

            #Parse out all the device tags for that device
            for tag in deviceTags:
                try:
                    deviceEntryPointer[tag] = str(device.getElementsByTagName(tag)[0].childNodes[0].data)
                except Exception, e:
                    if self.VERBOSE:
                        logging.debug( 'Device',deviceEntryPointer['fullName'],'does not have a',tag)
                    continue
            #Get a list of all services for this device listing
            self.parseServiceList(device,deviceEntryPointer,index)

        return

    #Parse the list of services specified in the XML file
    def parseServiceList(self,xmlRoot,device,index):
        serviceEntryPointer = False
        dictName = "services"
        serviceListTag = "serviceList"
        serviceTag = "service"
        serviceNameTag = "serviceType"
        serviceTags = ["serviceId","controlURL","eventSubURL","SCPDURL"]

        try:
            device[dictName] = {}
            #Get a list of all services offered by this device
            for service in xmlRoot.getElementsByTagName(serviceListTag)[0].getElementsByTagName(serviceTag):
                #Get the full service descriptor
                serviceName = str(service.getElementsByTagName(serviceNameTag)[0].childNodes[0].data)

                #Get the service name from the service descriptor string
                serviceDisplayName = self.parseServiceTypeName(serviceName)
                if not serviceDisplayName:
                    continue

                #Create new service entry for the device in ENUM_HOSTS
                serviceEntryPointer = device[dictName][serviceDisplayName] = {}
                serviceEntryPointer['fullName'] = serviceName

                #Get all of the required service info and add it to ENUM_HOSTS
                for tag in serviceTags:
                    serviceEntryPointer[tag] = str(service.getElementsByTagName(tag)[0].childNodes[0].data)

                #Get specific service info about this service
                self.parseServiceInfo(serviceEntryPointer,index)
        except Exception, e:
            logging.debug( 'Caught exception while parsing device service list:',e)

    #Parse details about each service (arguements, variables, etc)
    def parseServiceInfo(self,service,index):
        argIndex = 0
        argTags = ['direction','relatedStateVariable']
        actionList = 'actionList'
        actionTag = 'action'
        nameTag = 'name'
        argumentList = 'argumentList'
        argumentTag = 'argument'

        #Get the full path to the service's XML file
        xmlFile = self.ENUM_HOSTS[index]['proto'] + self.ENUM_HOSTS[index]['name']
        if not xmlFile.endswith('/') and not service['SCPDURL'].startswith('/'):
            xmlFile += '/'
        if self.ENUM_HOSTS[index]['proto'] in service['SCPDURL']:
            xmlFile = service['SCPDURL']
        else:
            xmlFile += service['SCPDURL']
        service['actions'] = {}

        #Get the XML file that describes this service
        (xmlHeaders,xmlData) = self.getXML(xmlFile)
        if not xmlData:
            logging.debug( 'Failed to retrieve service descriptor located at:',xmlFile)
            return False

        try:
            xmlRoot = minidom.parseString(xmlData)

            #Get a list of actions for this service
            try:
                actionList = xmlRoot.getElementsByTagName(actionList)[0]
            except:
                logging.debug( 'Failed to retrieve action list for service %s!' % service['fullName'])
                return False
            actions = actionList.getElementsByTagName(actionTag)
            if actions == []:
                logging.debug( 'Failed to retrieve actions from service actions list for service %s!' % service['fullName'])
                return False

            #Parse all actions in the service's action list
            for action in actions:
                #Get the action's name
                try:
                    actionName = str(action.getElementsByTagName(nameTag)[0].childNodes[0].data).strip()
                except:
                    logging.debug( 'Failed to obtain service action name (%s)!' % service['fullName'])
                    continue

                #Add the action to the ENUM_HOSTS dictonary
                service['actions'][actionName] = {}
                service['actions'][actionName]['arguments'] = {}

                #Parse all of the action's arguments
                try:
                    argList = action.getElementsByTagName(argumentList)[0]
                except:
                    #Some actions may take no arguments, so continue without raising an error here...
                    continue

                #Get all the arguments in this action's argument list
                arguments = argList.getElementsByTagName(argumentTag)
                if arguments == []:
                    if self.VERBOSE:
                        logging.debug( 'Action',actionName,'has no arguments!')
                    continue

                #Loop through the action's arguments, appending them to the ENUM_HOSTS dictionary
                for argument in arguments:
                    try:
                        argName = str(argument.getElementsByTagName(nameTag)[0].childNodes[0].data)
                    except:
                        logging.debug( 'Failed to get argument name for',actionName)
                        continue
                    service['actions'][actionName]['arguments'][argName] = {}

                    #Get each required argument tag value and add them to ENUM_HOSTS
                    for tag in argTags:
                        try:
                            service['actions'][actionName]['arguments'][argName][tag] = str(argument.getElementsByTagName(tag)[0].childNodes[0].data)
                        except:
                            logging.debug( 'Failed to find tag %s for argument %s!' % (tag,argName))
                            continue

            #Parse all of the state variables for this service
            self.parseServiceStateVars(xmlRoot,service)

        except Exception, e:
            logging.debug( 'Caught exception while parsing Service info for service %s: %s' % (service['fullName'],str(e)))
            return False

        return True

    #Get info about a service's state variables
    def parseServiceStateVars(self,xmlRoot,servicePointer):

        na = 'N/A'
        varVals = ['sendEvents','dataType','defaultValue','allowedValues']
        serviceStateTable = 'serviceStateTable'
        stateVariable = 'stateVariable'
        nameTag = 'name'
        dataType = 'dataType'
        sendEvents = 'sendEvents'
        allowedValueList = 'allowedValueList'
        allowedValue = 'allowedValue'
        allowedValueRange = 'allowedValueRange'
        minimum = 'minimum'
        maximum = 'maximum'

        #Create the serviceStateVariables entry for this service in ENUM_HOSTS
        servicePointer['serviceStateVariables'] = {}

        #Get a list of all state variables associated with this service
        try:
            stateVars = xmlRoot.getElementsByTagName(serviceStateTable)[0].getElementsByTagName(stateVariable)
        except:
            #Don't necessarily want to throw an error here, as there may be no service state variables
            return False

        #Loop through all state variables
        for var in stateVars:
            for tag in varVals:
                #Get variable name
                try:
                    varName = str(var.getElementsByTagName(nameTag)[0].childNodes[0].data)
                except:
                    logging.debug( 'Failed to get service state variable name for service %s!' % servicePointer['fullName'])
                    continue

                servicePointer['serviceStateVariables'][varName] = {}
                try:
                    servicePointer['serviceStateVariables'][varName]['dataType'] = str(var.getElementsByTagName(dataType)[0].childNodes[0].data)
                except:
                    servicePointer['serviceStateVariables'][varName]['dataType'] = na
                try:
                    servicePointer['serviceStateVariables'][varName]['sendEvents'] = str(var.getElementsByTagName(sendEvents)[0].childNodes[0].data)
                except:
                    servicePointer['serviceStateVariables'][varName]['sendEvents'] = na

                servicePointer['serviceStateVariables'][varName][allowedValueList] = []

                #Get a list of allowed values for this variable
                try:
                    vals = var.getElementsByTagName(allowedValueList)[0].getElementsByTagName(allowedValue)
                except:
                    pass
                else:
                    #Add the list of allowed values to the ENUM_HOSTS dictionary
                    for val in vals:
                        servicePointer['serviceStateVariables'][varName][allowedValueList].append(str(val.childNodes[0].data))

                #Get allowed value range for this variable
                try:
                    valList = var.getElementsByTagName(allowedValueRange)[0]
                except:
                    pass
                else:
                    #Add the max and min values to the ENUM_HOSTS dictionary
                    servicePointer['serviceStateVariables'][varName][allowedValueRange] = []
                    try:
                        servicePointer['serviceStateVariables'][varName][allowedValueRange].append(str(valList.getElementsByTagName(minimum)[0].childNodes[0].data))
                        servicePointer['serviceStateVariables'][varName][allowedValueRange].append(str(valList.getElementsByTagName(maximum)[0].childNodes[0].data))
                    except:
                        pass
        return True


def build_upnp_server_list ():
    global upnp_server_list, upnp_serv
    st = "upnp:rootdevice"
    myip = ''
    lport = upnp_serv.port

    request =   "M-SEARCH * HTTP/1.1\r\n"\
            "HOST:%s:%d\r\n"\
            "ST:%s\r\n" % (upnp_serv.ip,upnp_serv.port,st)
    for header,value in upnp_serv.msearchHeaders.iteritems():
            request += header + ':' + value + "\r\n"
    request += "\r\n"

    logging.debug("Entering discovery mode")

    server = upnp_serv.createNewListener(myip,lport)
    if server == False:
        logging.debug('Failed to bind port %d' % lport)
        return

    upnp_serv.send(request,server)

    #search for 5 seconds

    end = datetime.datetime.now() + datetime.timedelta(seconds=12)
    while datetime.datetime.now() < end:
        upnp_serv.parseSSDPInfo(upnp_serv.listen(1024,server),False,False)

    if upnp_serv.ENUM_HOSTS == 0:
        upnp_server_list = {}
        return False

    for index,hostInfo in upnp_serv.ENUM_HOSTS.iteritems():
        if hostInfo['dataComplete'] != True:
            #Get extended device and service information
            if hostInfo != False:
                logging.debug("Requesting device and service info for %s (this could take a few seconds)..." % hostInfo['name'])
                if hostInfo['dataComplete'] == False:
                    (xmlHeaders,xmlData) = upnp_serv.getXML(hostInfo['xmlFile'])
                    if xmlData == False:
                        logging.debug('Failed to request host XML file:',hostInfo['xmlFile'])
                    elif upnp_serv.getHostInfo(xmlData,xmlHeaders,index) == False:
                        logging.debug("Failed to get device/service info for %s..." % hostInfo['name'])
                    else:
                        logging.debug( 'Host data enumeration complete!')
                        item = upnp_server(index)
                        upnp_server_list[item.name]=item
    return upnp_server_list

upnp_serv = upnp(False,False,None)

class upnp_server:
    name = None
    index= None
    hostinfo= None

    def __init__(self,my_index):
        global upnp_serv
        logging.debug('Create index: %d' % my_index)
        self.index=my_index
        self.hostinfo=upnp_serv.ENUM_HOSTS[my_index]
        self.name="UPNP %d" % my_index
        if self.hostinfo['name']:
            self.name=self.hostinfo['name']

        for deviceName,deviceData in upnp_serv.ENUM_HOSTS[self.index]['deviceList'].iteritems():
            for k,v in deviceData.iteritems():
                try:
                    v.has_key(False)
                except:
                    logging.debug('%s=%s' % (k,v))
                    if k == "friendlyName":
                        self.name=v

        #name=hostinfo['deviceList']['deviceData'].['friendlyName']


