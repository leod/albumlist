import os
import sys
import locale
import pprint
import string

import pylast
import sqlite3
import mpd

import mutagen.easyid3
import mutagen.id3 
import mutagen.easymp4
import mutagen.flac
import mutagen.oggvorbis

from Cheetah.Template import Template

from config import *

def uniq(list):
	set = {}
	return [set.setdefault(x, x) for x in list if x not in set]

def is_in_sub(subdir, fname):
	return subdir == None or string.split(fname, "/")[0] == subdir

def get_artist(song):
	try:
		artist = song["albumartist"]
	except KeyError:
		artist = song["artist"]

	return artist

def get_tagger(fname):
	if fname.endswith(".mp3"):
		return mutagen.easyid3.EasyID3(fname)
	elif fname.endswith(".mp4") or fname.endswith(".m4a"):
		return mutagen.easymp4.EasyMP4(fname)
	elif fname.endswith(".flac"):
		return mutagen.flac.FLAC(fname)
	elif fname.endswith(".ogg"):
		return mutagen.oggvorbis.OggVorbis(fname)

def extract_cover(fname, to):
	if not fname.endswith(".mp3"): return (False, "")

	f = mutagen.id3.ID3(fname);

	for frame in f.getall("APIC"):
		ext = ".img"
		if (frame.mime == "image/jpeg") or (frame.mime == "image/jpg"): ext = ".jpg"
		if frame.mime == "image/png": ext = ".png"
		if frame.mime == "image/gif": ext = ".gif"

		to += ext

		if not os.path.exists(to):
			myfile = file(to, 'wb')
			myfile.write(frame.data)
			myfile.close()

	return (True, to)

def tag_all(songs, network, subdir, translate, whitelist, min_weight):
	tagcache = {}

	for song in songs:
		artist = ""
		try:
			artist = get_artist(song)
		except KeyError:
			continue

		if not song["file"].endswith(".m4a"):
			continue

		if not is_in_sub(subdir, song["file"]):
			continue

		tags = {}
		if not (artist in tagcache):
			fmartist = network.get_artist(artist)
			weighted_tags = fmartist.get_top_tags()
			weighted_tags.sort(lambda x, y: int(x.weight) > int(y.weight))
			
			for tag in weighted_tags:
				try:
					tag.item.name = translate[tag.item.name.lower()]
				except KeyError:
					pass

			filtered_tags = map(lambda x: x.item.name.title(), filter(lambda x: int(x.weight) > min_weight and x.item.name.lower() in whitelist, weighted_tags))
			tagcache[artist] = filtered_tags

			tags = uniq(filtered_tags)

			print "============= Setting '" + artist + "' to: " + str(tags)
		else:
			tags = tagcache[artist]

		print "Tagging: " + song["file"]
		tagger = get_tagger(DIRECTORY + song["file"])

		if tagger == None:
			print "no tagger for: " + song["file"]
			continue

		tagger["genre"] = tags
		tagger.save()

def create_genre_list(songs, directory, subdir=None, extract_covers=False):
	genres = {}

	for song in songs:
		if not ("genre" in song and "artist" in song and "title" in song and "album" in song):
			continue

		if not is_in_sub(subdir, song["file"]):
			continue

		artist = get_artist(song)

		if isinstance(song["genre"], str):
			song["genre"] = [song["genre"]]

		for genre in song["genre"]:
			if not genre in genres:
				genres[genre] = {}	
			if not artist in genres[genre]:
				genres[genre][artist] = []
			if not song["album"] in genres[genre][artist]:
				album = {}
				album["name"] = song["album"]
				cover_name = "cover/" + string.replace(string.replace(string.lower(song["artist"] + "_" + song["album"]), " ", "_"), "/", "_slash_")
				(success, fname) = extract_cover(directory + song["file"], cover_name)
				if success:
					album["cover"] = fname
				genres[genre][artist].append(album)

	return genres

def write_html(genres):
	template = Template(file="html.tmpl")
	template.genres = genres
	template.genres_sorted = sorted(genres.keys())
	
	print template	

network = pylast.LastFMNetwork(api_key = API_KEY, api_secret = API_SECRET)

mpd = mpd.MPDClient()
mpd.connect("127.0.0.1", 6600)
songs = mpd.listallinfo()

write_html(create_genre_list(songs, DIRECTORY, SUB_DIRECTORY))

#tag_all(songs, network, subdir=SUB_DIRECTORY, translate=TRANSLATE_TAGS, whitelist=TAG_WHITELIST, min_weight=TAG_MIN_WEIGHT)
