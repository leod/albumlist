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
	if os.path.exists(to + ".jpg"): return (True, to + ".jpg")
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

	return (False, "")

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

def clean_name(name):
	def f(c):
		if c.isalnum():
			return c
		else:
			return "_"
	return "".join(map(f, name))

class Genre(object):
	name = None
	clean_name = None
	artists = {}
	num_albums = 0

class Artist(object):
	name = None
	genre_names = []
	genres = []
	albums = {}

class Album(object):
	artst = None
	name = None
	cover_filename = None
	songs = []
	date = ""
	is_important = False

def create_artist_list(songs, directory, subdir=None, extract_covers=False):
	artists = {}

	for song in songs:
		if not ("genre" in song and "artist" in song and "title" in song and "album" in song):
			continue

		if not is_in_sub(subdir, song["file"]):
			continue

		if isinstance(song["genre"], str):
			song["genre"] = [song["genre"]]

		artist_name = get_artist(song)
		artist = None

		if not artist_name in artists:
			artist = Artist()
			artist.name = artist_name
			artist.genre_names = song["genre"];
			artist.albums = {}

			artists[artist_name] = artist
		else:
			artist = artists[artist_name]

		album_name = song["album"]
		album = None

		if not album_name in artist.albums:
			album = Album()
			album.artist = artist
			album.name = album_name
			album.date = ""

			if "date" in song:
				album.date = song["date"]
			
			if extract_covers:
				cover_name = "cover/" + clean_name(artist_name + "_" + album_name)
				(success, fname) = extract_cover(directory + song["file"], cover_name)
				if success:
					album.cover_filename = fname
				else:
					album.cover_filename = "cover/no_cover-large.jpg"
		else:
			album = artist.albums[album_name]

		album.songs.append(song)	

		artist.albums[album_name] = album

	return artists

def create_genre_list(artists):
	genres = {}
	num_albums = 0
	
	for artist in artists.values():
		artist.genres = []
		num_albums += len(artist.albums)

		for genre_name in artist.genre_names:
			genre = None

			if not genre_name in genres:
				genre = Genre()
				genre.name = genre_name
				genre.artists = {}
				genre.clean_name = clean_name(genre_name).lower()
				genre.num_albums = 0
				genre.is_important = False

				genres[genre_name] = genre
			else:
				genre = genres[genre_name]

			genre.num_albums += len(artist.albums)

			genre.artists[artist.name] = artist
			artist.genres.append(genre)
		assert len(artist.genre_names) == len(artist.genres)

	for genre in genres.values():
		print genre.num_albums / num_albums
		if genre.num_albums / float(num_albums) > 0.04:
			genre.is_important = True

	return genres

def write_html(genres):
	template = Template(file="html.tmpl")

	for genre in genres.values():
		print "Writing " + genre.clean_name

		template.genres = genres
		template.this_genre = genre

		out = open("html/" + genre.clean_name + ".html", "w")
		out.write(str(template))
		out.close()
		
network = pylast.LastFMNetwork(api_key = API_KEY, api_secret = API_SECRET)

mpd = mpd.MPDClient()
mpd.connect("127.0.0.1", 6600)
songs = mpd.listallinfo()

artists = create_artist_list(songs, DIRECTORY, SUB_DIRECTORY, True)
genres = create_genre_list(artists)

write_html(genres)

#tag_all(songs, network, subdir=SUB_DIRECTORY, translate=TRANSLATE_TAGS, whitelist=TAG_WHITELIST, min_weight=TAG_MIN_WEIGHT)
