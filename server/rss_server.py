#!/usr/bin/env python
# Copyright 2010, Brian Taylor
# Distribute under the terms of the GNU General Public License
# Version 2 or better


# this file contains the configurable variables
config_file = "config.ini"
LOG_FILE = "my_media_log.txt"

#transcoding subproccess state
tc_proc = None
tc_fname = None
tc_f = None


# main webapp
import os
import re
import web
from PyRSS2Gen import *
import eyeD3
import urllib
import ConfigParser
import math
import logging
from common import *
from upnp import *
import subprocess
import time

logging.basicConfig(filename=LOG_FILE, level=logging.DEBUG)
#formatter = logging.Formatter("%(levelname)@s[%(asctime)s]: %(message)s")
#logging.getLogger().setFormatter(formatter)


class PublishMixin:
  def publish_extensions(self, handler):
    for name in self.TAGS:
      val = getattr(self, name)
      if val:
        handler.startElement(name, {})
        handler.characters(val)
        handler.endElement(name)

  def set_variables(self, kwargs):
    for name in self.TAGS:
      if name in kwargs:
        setattr(self, name, kwargs[name])
        del kwargs[name]
      else:
        setattr(self, name, None)

class RSSImageItem(PublishMixin, RSSItem):
  "extending rss items to support our extended tags"
  def __init__(self, **kwargs):
    self.TAGS = ('image', 'filetype', 'tracknum')
    self.set_variables(kwargs)
    RSSItem.__init__(self, **kwargs)

class RSSDoc(PublishMixin, RSS2):
  "extending rss document to provide theme tags, etc"
  def __init__(self, **kwargs):
    self.TAGS = ('theme',)
    self.set_variables(kwargs)
    RSS2.__init__(self, **kwargs)

def main_menu_feed(config):
  "create the root feed for the main menu"
  global unpn_server_list

  items = []
  item = dir2item("music", music_dir(config), music_dir(config), config, image=None, name="My Music")
  item.image = "%s/media?%s" % (server_base(config), urllib.urlencode({'name': "images/music_square.jpg", 'key': "client"}))
  items.append(item)

  dir = video_dir(config)
  if dir and os.path.exists(dir):
    item = dir2item("video", dir, dir, config, image=None, name="My Video")
    item.image = "%s/media?%s" % (server_base(config), urllib.urlencode({'name': "images/videos_square.jpg", 'key': "client"}))
    items.append(item)

  #UPNP is enabled
  if use_upnp(config):
      #something was found
      if build_upnp_server_list():
          #build list
          for name,server in upnp_server_list.iteritems():
            if server.name:
                logging.debug("Adding UPNP device: "+server.name)
                item = dir2item("upnp", server.index, server.index, config, image=None, name=server.name)
                item.image = "%s/media?%s" % (server_base(config), urllib.urlencode({'name': "images/videos_square.jpg", 'key': "client"}))
                items.append(item)
      else:
          logging.debug("No UPNP devices detected")
  else:
      logging.debug("UPNP Disbaled in config. Set use_upnp = True to enable")

  doc = RSSDoc(
      title="A Personal Music Feed",
      link="%s/feed" % server_base(config),
      description="My Media",
      lastBuildDate=datetime.datetime.now(),
      items = items,
      theme = "media")

  return doc

def file2item(key, fname, base_dir, config, image=None):
  if not os.path.exists(fname):
    logging.warning("WARNING: Tried to create feed item for `%s' which does not exist. This shouldn't happen" % fname)
    return None

  # guess the filetype based on the extension
  ext = os.path.splitext(fname)[1].lower()

  title = "None"
  description = "None"
  filetype = None
  mimetype = None
  tracknum = None

  if ext == ".mp3":
    # use the ID3 tags to fill out the mp3 data

    try:
      tag = eyeD3.Tag()
      if not tag.link(fname):
        return None
    except:
      logging.warning("library failed to parse ID3 tags for %s. Skipping." % fname)
      return None

    title = tag.getTitle()
    description = tag.getArtist()

    tracknum = tag.getTrackNum()[0]
    if tracknum:
      tracknum = str(tracknum)

    filetype = "mp3"

  elif ext == ".wma":
    # use the filename as the title

    basename = os.path.split(fname)[1]
    title = os.path.splitext(basename)[0]
    description = ""
    filetype = "wma"

  elif ext in (".m4v", ".mp4", ".mov"):
    # this is a video file

    basename = os.path.split(fname)[1]
    title = os.path.splitext(basename)[0]
    description = "Video"
    filetype = "mp4"

  elif ext in (".mpeg", ".mpg", ".mpeg2", ".iso", ".wmv", ".asf", ".flv"):
    # this is a video file to transcode

    basename = os.path.split(fname)[1]
    title = os.path.splitext(basename)[0]
    description = "Transcoded Video"
    filetype = "mp4"
    key = "tc"

  else:
    # don't know what this is

    return None

  size = os.stat(fname).st_size
  path = relpath26(fname, base_dir)
  link="%s/media?%s" % (server_base(config), urllib.urlencode({'name':to_utf8(path), 'key': key}))

  if image:
    image = relpath26(image, base_dir)
    image = "%s/media?%s" % (server_base(config), urllib.urlencode({'name':to_utf8(image), 'key': key}))

  logging.debug(link)

  return RSSImageItem(
      title = title,
      link = link,
      enclosure = Enclosure(
        url = link,
        length = size,
        type = ext2mime(ext)),
      description = description,
      guid = Guid(link, isPermaLink=0),
      pubDate = datetime.datetime.now(),
      image = image,
      filetype = filetype,
      tracknum = tracknum)

def dir2item(key, dname, base_dir, config, image, name=None):
  if key!="upnp":
      path = relpath26(dname, base_dir)

      link = "%s/feed?%s" % (server_base(config), urllib.urlencode({'dir':to_utf8(path), 'key': key}))

      if not name:
        name = os.path.split(dname)[1]

      if image:
        image = relpath26(image, base_dir)
        image = "%s/media?%s" % (server_base(config), urllib.urlencode({'name':to_utf8(image), 'key': key}))

      description = "Folder"
      #if image:
      #  description += "<img src=\"%s\" />" % image
  else:
      path = base_dir + dname

      link = "%s/feed?%s" % (server_base(config), urllib.urlencode({'dir':to_utf8(path), 'key': key}))

      if not name:
        name = os.path.split(dname)[1]

      if image:
        image = relpath26(image, base_dir)
        image = "%s/media?%s" % (server_base(config), urllib.urlencode({'name':to_utf8(image), 'key': key}))

      description = "UPNP Folder"

  return RSSImageItem(
      title = name,
      link = link,
      description = description,
      guid = Guid(link, isPermaLink=0),
      pubDate = datetime.datetime.now(),
      image = image)

def getart(path):
  path = to_unicode(path)

  # is path a full path to a video?
  if is_video(path):
    no_ext = os.path.splitext(path)[0]

    # look for a corresponding image
    for test_ext in (".jpg", ".jpeg", ".png"):
      if os.path.exists(no_ext + test_ext):
        return no_ext + test_ext
    return None

  curr_image = None
  img_re = re.compile("\.jpg|\.jpeg|\.png")

  for base, dirs, files in os.walk(path):
    # don't recurse when searching for artwork
    del dirs[:]

    for file in files:
      ext = os.path.splitext(file)[1]
      if ext and img_re.match(ext):
        curr_image = os.path.join(base,file)
        break

  return curr_image

# we could memoize getart as a primitive form of caching since
# the return value if this is unlikely to change

def item_sorter(lhs, rhs):
  "folders first, sort on artist, then track number (prioritize those with), then track name"

  # folders always come before non folders
  if lhs.description == "Folder" and rhs.description != "Folder":
    return -1
  if rhs.description == "Folder" and lhs.description != "Folder":
    return 1

  # first sort by artist
  if lhs.description.lower() < rhs.description.lower():
    return -1
  if rhs.description.lower() < lhs.description.lower():
    return 1

  # things with track numbers always come first
  if lhs.tracknum and not rhs.tracknum:
    return -1
  if rhs.tracknum and not lhs.tracknum:
    return 1

  # if both have a track number, sort on that
  if lhs.tracknum and rhs.tracknum:
    if int(lhs.tracknum) < int(rhs.tracknum):
      return -1
    elif int(lhs.tracknum) > int(rhs.tracknum):
      return 1

  # if the track numbers are the same or both don't
  # exist then sort by title
  if lhs.title.lower() < rhs.title.lower():
    return -1
  elif rhs.title.lower() < lhs.title.lower():
    return 1
  else:
    return 0 # they must be the same

def partition_by_firstletter(key, subdirs, basedir, minmax, config):
  "based on config, change subdirs into alphabet clumps if there are too many"

  max_dirs = 10
  if config.has_option("config", "max_folders_before_split"):
    max_dirs = int(config.get("config", "max_folders_before_split"))

  # handle the trivial case
  if len(subdirs) <= max_dirs or max_dirs <= 0 or not minmax:
    return subdirs

  # figure out if we're doing a letter or number partition
  minl, maxl = minmax

  if is_letter(minl):
    min_of_class = 'a'
  elif is_number(minl):
    min_of_class = '0'
  else:
    # this must be a special character. give up
    return subdirs

  # presort
  subdirs.sort(key=lambda x: x.title.lower())

  # how many pivots? (round up)
  pivots = int(math.ceil(float(len(subdirs))/max_dirs))
  newsubdirs = []

  def get_letter(item):
    return first_letter(item.title)

  last_index_ord = len(subdirs) - 1
  last_end = 0

  # try to divide the list evenly
  for sublist in range(pivots):
    if last_end == last_index_ord:
      break # we're done

    last_letter = get_letter(subdirs[last_end])
    if last_end == 0:
      last_letter = minl

    next_end = min(last_end + max_dirs, len(subdirs) - 1)

    while get_letter(subdirs[next_end]) == last_letter and next_end != last_index_ord:
      next_end += 1

    first_unique = get_letter(subdirs[next_end])

    while get_letter(subdirs[next_end]) == first_unique and next_end != last_index_ord:
      next_end += 1

    next_letter = chr(max(ord(min_of_class), ord(get_letter(subdirs[next_end]))-1))
    if next_end == last_index_ord:
      next_letter = maxl

    # create the item
    link = "%s/feed?%s" % (server_base(config), urllib.urlencode({'dir':basedir, 'range': last_letter+next_letter, 'key': key}))

    newsubdirs.append(RSSImageItem(
      title = "%s - %s" % (last_letter.upper(), next_letter.upper()),
      link = link,
      description = "Folder",
      guid = Guid(link, isPermaLink=0)))

    last_end = next_end

  if len(newsubdirs) > 1:
    return newsubdirs
  else:
    return subdirs

def getdoc(key, path, base_dir, dirrange, config, recurse=False):
  "get a media feed document for path"

  # make sure we're unicode
  path = to_unicode(path)

  number_subdirs = []
  letter_subdirs = []
  special_subdirs = []

  items = []

  if dirrange:
    minl, maxl = dirrange
    minl = minl.lower()
    maxl = maxl.lower()

  media_re = re.compile("\.mp3|\.wma|\.m4v|\.mp4|\.mov|\.mpeg|\.mpg|\.mpeg2|\.iso|\.wmv|\.asf|\.flv")

  for base, dirs, files in os.walk(path):
    if not recurse:
      for dir in dirs:

        # skip directories not in our range
        first_chr = first_letter(dir)
        if dirrange and (first_chr < minl or first_chr > maxl):
          continue

        subdir = os.path.join(base,dir)
        item = dir2item(key, subdir, base_dir, config, getart(subdir))
        if is_number(first_chr):
          number_subdirs.append(item)
        elif is_letter(first_chr):
          letter_subdirs.append(item)
        else:
          special_subdirs.append(item)

      del dirs[:]

    # first pass to find images
    curr_image = getart(base)

    for file in files:
      if not media_re.match(os.path.splitext(file)[1].lower()):
        logging.debug("rejecting %s" % file)
        continue

      path = os.path.join(base, file)

      if is_video(path):
        image_icon = getart(path) or curr_image
      else:
        image_icon = curr_image

      item = file2item(key, path, base_dir, config, image_icon)
      if item:
        items.append(item)

  # include our partitioned folders
  if dirrange:
    # the range must either have only letters or only numbers
    if len(number_subdirs) > 0:
      items.extend(partition_by_firstletter(key, \
          number_subdirs, path, (minl,maxl), config))
    elif len(letter_subdirs) > 0:
      items.extend(partition_by_firstletter(key, \
          letter_subdirs, path, (minl,maxl), config))
  else:
    items.extend(partition_by_firstletter(key, number_subdirs, path, ('0','9'), config))
    items.extend(partition_by_firstletter(key, letter_subdirs, path, ('a','z'), config))

  items.extend(special_subdirs)

  # sort the items
  items.sort(item_sorter)

  if dirrange:
    range = "&range=%s" % (minl + maxl)
  else:
    range = ""

  doc = RSSDoc(
      title="A Personal Music Feed",
      link="%s/feed?key=%s&dir=%s%s" % (key, server_base(config), relpath26(path, base_dir), range),
      description="My Media",
      lastBuildDate=datetime.datetime.now(),
      items = items,
      theme = key)

  return doc

def doc2m3u(doc):
  "convert an rss feed document into an m3u playlist"

  lines = []
  for item in doc.items:
    lines.append(item.link)
  return "\n".join(lines)

def range_handler(fname):
  "return all or part of the bytes of a file depending on whether we were called with the HTTP_RANGE header set"

  logging.debug("open file: "+fname)
  f = open(fname, "rb")
  if not isinstance(f, file):
    logging.debug("range_handler: Invalid file handle")
  else:
    logging.debug("range_handler: Valid file handle")

  bytes = None
  CHUNK_SIZE = 10 * 1024;


  # is this a range request?
  # looks like: 'HTTP_RANGE': 'bytes=41017-'
  if 'HTTP_RANGE' in web.ctx.environ:
    logging.debug("server issued range query: %s" % web.ctx.environ['HTTP_RANGE'])

    # try a start only regex
    regex = re.compile('bytes=(\d+)-$')
    grp = regex.match(web.ctx.environ['HTTP_RANGE'])
    if grp:
      start = int(grp.group(1))
      logging.debug("player issued range request starting at %d" % start)

      f.seek(start)

      # we'll stream it
      bytes = f.read(CHUNK_SIZE)
      while not bytes == "":
        yield bytes
        bytes = f.read(CHUNK_SIZE)

      f.close()

    # try a span regex
    regex = re.compile('bytes=(\d+)-(\d+)$')
    grp = regex.match(web.ctx.environ['HTTP_RANGE'])
    if grp:
      start,end = int(grp.group(1)), int(grp.group(2))
      logging("player issued range request starting at %d and ending at %d" % (start, end))

      f.seek(start)
      bytes_remaining = end-start+1 # +1 because range is inclusive
      chunk_size = min(bytes_remaining, chunk_size)
      bytes = f.read(chunk_size)

      while not bytes == "":
        yield bytes

        bytes_remaining -= chunk_size
        chunk_size = min(bytes_remaining, chunk_size)
        bytes = f.read(chunk_size)

      f.close()

    # try a tail regex
    regex = re.compile('bytes=-(\d+)$')
    grp = regex.match(web.ctx.environ['HTTP_RANGE'])
    if grp:
      end = int(grp.group(1))
      logging.debug("player issued tail request beginning at %d from end" % end)

      f.seek(-end, os.SEEK_END)
      bytes = f.read()
      yield bytes
      f.close()

  else:
    # write the whole thing
    # we'll stream it
    logging.debug("Stream whole file")
    bytes = f.read(CHUNK_SIZE)
    while not bytes == "":
      yield bytes
      bytes = f.read(CHUNK_SIZE)

    f.close()

def range_handler_tc(fname):
  "transcode and return all or part of the bytes of a file depending on whether we were called with the HTTP_RANGE header set"
  global tc_proc, tc_fname, tc_f
  config = parse_config(config_file)
  file_out = tc_file(config)

  allow_head=True
  allow_span=True
  allow_tail=True

  logging.debug("trancode file: " + fname)

  if fname != tc_fname or tc_proc == None:
    if tc_proc != None and tc_proc.poll() == None:
        logging.debug('End Transcode: '+ tc_fname)
        tc_f.close()
        tc_proc.terminate()
        subprocess.Pclose(tc_proc)
        if file_out != "PIPE":
            tc_proc.wait()
        else:
            time.sleep(15)
            if tc_proc.poll() == None:
                tc_proc.kill()

    tc_fname = fname
    logging.debug('Start new transcode of: ' + tc_fname)

    tc_cmd = tc_path(config) + ' "' + tc_fname + '" ' + tc_args(config)
    logging.debug('Running: ' + tc_cmd)

    if file_out == "PIPE":
        #transcoding via STDOUT
        tc_proc = subprocess.Popen(tc_cmd,shell=True,bufsize=-1,stdout=subprocess.PIPE)
        tc_f = tc_proc.stdout
        logging.debug("Use sdtout for open")
    else:
        #transcoding via fixed file
        tc_proc = subprocess.Popen(tc_cmd,shell=True)
        tc_f = open(file_out, "rb")
        logging.debug("Opened: " + file_out)
  else:
    logging.debug("Send more of: " + tc_fname)

  f=tc_f
  if not isinstance(f, file):
    logging.debug("range_handler_for_file: Invalid file handle")


  #if running, no tail calls
  if tc_proc.poll() == None:
    allow_tail=False


  bytes = None
  CHUNK_SIZE = 10 * 1024;
  #CHUNK_SIZE = 5 * 1024;


  # is this a range request?
  # looks like: 'HTTP_RANGE': 'bytes=41017-'
  if 'HTTP_RANGE' in web.ctx.environ:
    logging.debug("server issued range query: %s" % web.ctx.environ['HTTP_RANGE'])


    # try a start only regex
    regex = re.compile('bytes=(\d+)-$')
    grp = regex.match(web.ctx.environ['HTTP_RANGE'])
    if grp and allow_head:
        logging.debug("Stream Head")

        start = int(grp.group(1))
        logging.debug("player issued range request starting at %d" % start)

        f.seek(start)

        # we'll stream it

        while True:
            bytes = f.read(CHUNK_SIZE)
            while not bytes == "":
              if bytes!= "":
                  logging.debug("Stream Head: yielding data")
                  yield bytes
              bytes = f.read(CHUNK_SIZE)
            if tc_proc.poll() != None:
                break

        done = True


    # try a span regex
    regex = re.compile('bytes=(\d+)-(\d+)$')
    grp = regex.match(web.ctx.environ['HTTP_RANGE'])
    if grp and allow_span:
      logging.debug("Stream Span")

      start,end = int(grp.group(1)), int(grp.group(2))
      logging("player issued range request starting at %d and ending at %d" % (start, end))

      f.seek(start)
      bytes_remaining = end-start+1 # +1 because range is inclusive
      chunk_size = min(bytes_remaining, chunk_size)

      while True:
        bytes = f.read(chunk_size)
        while not bytes == "":
          if bytes!= "":
              logging.debug("Stream Span: yielding data")
              yield bytes

          bytes_remaining -= chunk_size
          chunk_size = min(bytes_remaining, chunk_size)
          bytes = f.read(chunk_size)
        if tc_proc.poll() != None:
            break

      done = True

    # try a tail regex
    regex = re.compile('bytes=-(\d+)$')
    grp = regex.match(web.ctx.environ['HTTP_RANGE'])
    if grp and allow_tail:
      logging.debug("Stream Tail")

      end = int(grp.group(1))
      logging.debug("player issued tail request beginning at %d from end" % end)

      f.seek(-end, os.SEEK_END)
      bytes = f.read()
      if bytes!= "":
          logging.debug("Stream Tail: yielding data")
          yield bytes

      done = True


  else:
    done = False

  if not done:
    # write the whole thing
    # we'll stream it
    logging.debug("Stream All: %s" % web.ctx.environ)
    f.seek(0)
    while True:
        bytes = f.read(CHUNK_SIZE)
        while not bytes == "":
            if bytes!= "":
                logging.debug("Stream All: yielding data")
                yield bytes
            bytes = f.read(CHUNK_SIZE)
        if tc_proc.poll() != None:
            break




class MediaHandler:
  "retrieve a song"

  def GET(self):
    song = web.input(name = None, key = None)
    if not song.name:
      return
    config = parse_config(config_file)
    name = song.name

    name = key_to_path(config, song.key, name)
    if not (name and os.path.exists(name)):
      return None

    # refuse anything that isn't in the media directory
    # IE, refuse anything containing pardir
    fragments = song.name.split(os.sep)
    if os.path.pardir in fragments:
      logging.warning("SECURITY WARNING: Someone was trying to access %s. The MyMedia client shouldn't do this" % song.name)
      return

    size = os.stat(name).st_size

    # make a guess at mime type
    ext = os.path.splitext(os.path.split(name)[1] or "")[1].lower()

    mimetype = ext2mime(ext)
    if not mimetype:
      return None

    if song.key == "tc" and mimetype == "video/mp4":
        #size = 0
        web.header("Content-Type", mimetype)
        #web.header("Content-Length", "%d" % size)
        return range_handler_tc(name)
    else:
        web.header("Content-Type", mimetype)
        web.header("Content-Length", "%d" % size)
        return range_handler(name)


class RssHandler:
  def GET(self):
    "retrieve a specific feed"

    config = parse_config(config_file)
    collapse_collections = config.get("config", "collapse_collections").lower() == "true"

    web.header("Content-Type", "application/rss+xml")
    feed = web.input(dir = None, range=None, key=None)

    if not feed.key in ("music", "video"):
      return main_menu_feed(config).to_xml()

    # get the range for partitioning
    range = feed.range
    if range: range = tuple(range)

    base_dir = key_to_path(config, feed.key)

    if feed.dir:
      # the user has navigated to dir
      path = os.path.join(base_dir, feed.dir)
      return getdoc(feed.key, path, base_dir, range, config, collapse_collections).to_xml()
    else:
      # if no dir was given we return the index view for this base_dir
      return getdoc(feed.key, base_dir, base_dir, range, config).to_xml()

class M3UHandler:
  def GET(self):
    "retrieve a feed in m3u format"

    config = parse_config(config_file)

    web.header("Content-Type", "text/plain")
    feed = web.input(dir = None)
    if feed.dir:
      path = os.path.join(music_dir(config), feed.dir)
      return doc2m3u(getdoc("music", path, music_dir(config), config, True))
    else:
      return doc2m3u(getdoc("music", music_dir(config), music_dir(config), config, True))

urls = (
    '/feed', 'RssHandler',
    '/media', 'MediaHandler',
    '/m3u', 'M3UHandler')

app = web.application(urls, globals())

if __name__ == "__main__":
  import sys

  config = parse_config(config_file)

  sys.argv.append(config.get("config","server_port"))
  app.run()
