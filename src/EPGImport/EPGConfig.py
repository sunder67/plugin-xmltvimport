import os
import log
from xml.etree.cElementTree import ElementTree, Element, SubElement, tostring, iterparse
from Tools.Directories import fileExists
import cPickle as pickle
import gzip
import time
import random

# User selection stored here, so it goes into a user settings backup
SETTINGS_FILE = '/etc/enigma2/epgimport.conf'
channelCache = {}

def isLocalFile(filename):
	# we check on a '://' as a silly way to check local file
	return '://' not in filename

def getChannels(path, name):
	global channelCache
	if name in channelCache:
		return channelCache[name]
	dirname, filename = os.path.split(path)
	if name:
		if isLocalFile(name):
			channelfile = os.path.join(dirname, name)
		else:
			channelfile = name
	else:
		channelfile = os.path.join(dirname, filename.split('.', 1)[0] + '.channels.xml')
	try:
		return channelCache[channelfile]
	except KeyError:
		pass
	c = EPGChannel(channelfile)
	channelCache[channelfile] = c
	return c


class EPGChannel:
	def __init__(self, filename, urls=None):
		self.mtime = None
		self.name = filename
		if urls is None:
			self.urls = [filename]
		else:
			self.urls = urls
		self.items = None
	def openStream(self, filename):
		fd = open(filename, 'rb')
		if not os.fstat(fd.fileno()).st_size:
			raise Exception, "File is empty"
		if filename.endswith('.gz'):
			fd = gzip.GzipFile(fileobj = fd, mode = 'rb')
		return fd
	def parse(self, filterCallback, downloadedFile):
		print>>log,"[EPGImport] Parsing channels from '%s'" % self.name
		self.items = {}
		for event, elem in iterparse(self.openStream(downloadedFile)):
			if elem.tag == 'channel':
				id = elem.get('id')
				ref = elem.text
				if id and ref:
					ref = ref.encode('latin-1')
					if filterCallback(ref):
						if self.items.has_key(id):
							self.items[id].append(ref)
						else:
							self.items[id] = [ref]
				elem.clear()
	def update(self, filterCallback, downloadedFile=None):
		if downloadedFile is not None:
			self.mtime = time.time()
			return self.parse(filterCallback, downloadedFile)
		elif (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			mtime = os.path.getmtime(self.urls[0])
			if (not self.mtime) or (self.mtime < mtime):
				self.parse(filterCallback, self.urls[0])
				self.mtime = mtime
	def downloadables(self):
		if (len(self.urls) == 1) and isLocalFile(self.urls[0]):
			return None
		else:
			# Check at most once a day
			now = time.time()
			if (not self.mtime) or (self.mtime + 86400 < now):
				return self.urls
		return None
	def __repr__(self):
		return "EPGChannel(urls=%s, channels=%s, mtime=%s)" % (self.urls, self.items and len(self.items), self.mtime)

class EPGSource:
	def __init__(self, path, elem):
		self.parser = elem.get('type')
		self.urls = [e.text.strip() for e in elem.findall('url')]
		self.url = random.choice(self.urls)
		self.description = elem.findtext('description')
		if not self.description:
			self.description = self.url
		self.format = elem.get('format', 'xml')
		self.channels = getChannels(path, elem.get('channels'))

def enumSourcesFile(sourcefile, filter=None):
	result = ""
	global channelCache
	for event, elem in iterparse(open(sourcefile, 'rb')):
		if elem.tag == 'source':
			s = EPGSource(sourcefile, elem)
			elem.clear()
			if (filter is None) or (s.description in filter):
				yield s
		elif elem.tag == 'channel':
			name = elem.get('name')
			urls = [e.text.strip() for e in elem.findall('url')]
			if name in channelCache:
				channelCache[name].urls = urls
			else:
				channelCache[name] = EPGChannel(name, urls)

def enumSources(path, filter=None):
	try:
		for sourcefile in os.listdir(path):
			if sourcefile.endswith('.sources.xml') and not sourcefile.startswith('rytec'):
				sourcefile = os.path.join(path, sourcefile)
				print>>log, "[EPGImport] using source",sourcefile
				try: 
					for s in enumSourcesFile(sourcefile, filter):
						yield s
				except Exception, e:
					print>>log, "[EPGImport] failed to open", sourcefile, "Error:", e
		if fileExists(os.path.join(path, 'sourcelist')):
			import random
			count = 0
			sourcelist = file(os.path.join(path, 'sourcelist')).readlines()
			noofsources = int(len(sourcelist))
			while (count < noofsources):
				try: 
					sourcefile = random.choice(sourcelist)
					sourcefile = sourcefile.replace("\n","")
					sourcefiletmp = sourcefile.replace("\n","")
					print>>log, "[EPGImport] using source",sourcefile
					import urllib
					sourcefile,headers = urllib.urlretrieve(sourcefile)
					for s in enumSourcesFile(sourcefile, filter):
						yield s
					count = noofsources + 1
				except Exception, e:
					print>>log, "[EPGImport] source is unavailble"
					sourcelist = [l for l in sourcelist if sourcefiletmp not in l]
					count = count + 1
					if count == 3:
						print>>log, "[EPGImport] all online sources are unavailble."
	except Exception, e:
		print>>log, "[EPGImport] failed to list", path, "Error:", e


def loadUserSettings(filename = SETTINGS_FILE):
	try:
		return pickle.load(open(filename, 'rb'))
	except Exception, e:
		print>>log, "[EPGImport] No settings", e
		return {"sources": []}

def storeUserSettings(filename = SETTINGS_FILE, sources = None):
	container = {"sources": sources}
	pickle.dump(container, open(filename, 'wb'), pickle.HIGHEST_PROTOCOL)

      
if __name__ == '__main__':
	import sys
	x = []
	l = []
	path = '.'
	if len(sys.argv) > 1:
		path = sys.argv[1]
	for p in enumSources(path):
		t = (p.description, p.urls, p.parser, p.format, p.channels)
		l.append(t)  
		print t
		x.append(p.description)
	storeUserSettings('settings.pkl', [1,"twee"])
	assert loadUserSettings('settings.pkl') == {"sources": [1,"twee"]}
	os.remove('settings.pkl')
	for p in enumSources(path, x):
		t = (p.description, p.urls, p.parser, p.format, p.channels)
		assert t in l
		l.remove(t)
	assert not l 	
	for name,c in channelCache.items():
		print "Update:", name
		c.update()
		print "# of channels:", len(c.items)
