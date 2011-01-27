import os
import sys
import locale
import pprint
import string
import pickle
import math
import re

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

def levenshtein(a,b):
    "Calculates the Levenshtein distance between a and b."
    n, m = len(a), len(b)
    if n > m:
        # Make sure n <= m, to use O(min(n,m)) space
        a,b = b,a
        n,m = m,n
        
    current = range(n+1)
    for i in range(1,m+1):
        previous, current = current, [i]+[0]*n
        for j in range(1,n+1):
            add, delete = previous[j]+1, current[j-1]+1
            change = previous[j-1]
            if a[j-1] != b[i-1]:
                change = change + 1
            current[j] = min(add, delete, change)
            
    return current[n]

def is_in_sub(subdir, fname):
	return subdir == None or string.split(fname, "/")[0] == subdir

def get_artist(song):
	try:
		artist = song["albumartist"]
	except KeyError:
		artist = song["artist"]

	return unicode(artist, "utf-8")

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
	weight = 0 # 0-9

class Artist(object):
	name = None
	genre_names = []
	genres = []
	albums = {}

	scrobbles = 0
	listeners = 0

class Album(object):
	artst = None
	name = None
	cover_filename = None
	songs = []
	date = ""
	is_important = False
	scrobbles = 0
	times_listened = 0.0

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

		album_name = unicode(song["album"], "utf-8")
		album = None

		if not album_name in artist.albums:
			album = Album()
			album.artist = artist
			album.name = album_name
			album.date = ""
			album.scrobbles = 0
			album.songs = []

			if "date" in song:
				album.date = song["date"]
			
			if extract_covers:
				cover_name = "cover/" + clean_name(artist.name + "_" + album_name)
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
		if genre.num_albums / float(num_albums) > 0.04:
			genre.is_important = True

	# Weigh genres
	max_albums = reduce(lambda x, y: max(x, y), map(lambda g: g.num_albums, genres.values()))
	min_albums = reduce(lambda x, y: min(x, y), map(lambda g: g.num_albums, genres.values()))

	for genre in genres.values():
		weight = (math.log(genre.num_albums) - math.log(min_albums)) / (math.log(max_albums) - math.log(min_albums))
		genre.weight = int(9 * weight)
		assert genre.weight in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]

	return genres

def write_html(genres):
	template = Template(file="html.tmpl")

	for genre in genres.values():
		#print "Writing " + genre.clean_name

		template.genres = genres
		template.this_genre = genre

		out = open("html/" + genre.clean_name + ".html", "w")
		out.write(str(template))
		out.close()

def fetch_stats(artists, network):
	library = pylast.Library(USER, network)

	lower_artists = dict(zip(map(lambda s: s.lower(), artists.keys()), artists.values()))

	print "Loading album scrobbles..."
	fm_albums = library.get_albums(limit=2000)
	print "Done. Loaded " + str(len(fm_albums)) + " albums."

	num_notfound = 0
	for fm_album in fm_albums:
		try:
			fm_artist_name = fm_album.item.get_artist().get_name().lower()
			artist = None

			# TODO: ...
			try:
				artist = lower_artists[fm_artist_name]
			except KeyError:
				try:
					artist = lower_artists[fm_artist_name.replace("&", "and")]
				except KeyError:
					try:
						artist = lower_artists[fm_artist_name.replace("+", "and")]
					except KeyError:
						try:
							artist = lower_artists[ARTIST_NAME_FIXES[fm_artist_name].lower()]
						except KeyError:
							artist = lower_artists[fm_artist_name.replace("and", "&")]

			def try_find(artist, name, f=None):
				if f == None: f = lambda x: x
				name = name.lower().strip()
				for album_name, album in artist.albums.items():
					if f(album_name).lower() == name:
						return album

			name = fm_album.item.get_name()
			local_album = try_find(artist, name)

			def remove_brackets(s):
				return re.sub('\[.*?\]', '', s)
			def remove_parens(s):
				return re.sub('\(.*?\)', '', s)
			def remove_colon_and_following(s):
				return re.sub(':.*$', '', s)

			if local_album == None:
				try:
					name = ALBUM_NAME_FIXES[fm_album.item.get_artist().get_name().lower()][name.lower()]
					local_album = try_find(artist, name)
				except KeyError:
					pass
			if local_album == None:
				name = remove_brackets(name)
				local_album = try_find(artist, name)
			if local_album == None:
				name = remove_parens(name)
				local_album = try_find(artist, name)
			if local_album == None:
				name = remove_colon_and_following(name)
				local_album = try_find(artist, name, remove_colon_and_following)
			if local_album == None:
				name = name.replace('?', '')
				local_album = try_find(artist, name)
			if local_album == None:
				name = "The " + name
				local_album = try_find(artist, name)
			if local_album == None:
				best_distance = None
				best_match = None
				for album_name, album in artist.albums.items():
					distance = levenshtein(album_name.lower(), fm_album.item.get_name().lower())
					if best_match == None or distance < best_distance:
						best_match = album
						best_distance = distance
				local_album = best_match	
				#print "Closest match to " + fm_album.item.get_name() + ": " + best_match.name + " (distance: " + str(best_distance) + ")"

			if local_album != None:
				#print "Adding " + str(fm_album.playcount) + " scrobbles to " + local_album.name
				local_album.scrobbles += fm_album.playcount
			else:
				#print "Didn't find " + fm_album.item.get_artist().get_name() +  " - " + fm_album.item.get_name()
				num_notfound += 1
		except KeyError:
			#print "=== Didn't find " + fm_album.item.get_artist().get_name()
			num_notfound += 1

	print str(num_notfound) + " albums were not found"	
	
	print "Loading artist scrobbles..."
	fm_artists = library.get_artists(limit=1000) # limit=None does not work
	print "Done. Loaded " + str(len(fm_artists)) + " artists."

	#for fm_artist in fm_artists:
		#try:
			#print fm_artist.item.get_name() + ": " + str(fm_artist.playcount)
			#lower_artists[string.lower(fm_artist.item.get_name())].scrobbles = fm_artist.playcount
		#except KeyError:
		#	print "Didn't find " + fm_artist.item.get_name()

	for artist_name, artist in artists.items():
		fm_artist = pylast.Artist(artist_name, network)
		artist.listeners = fm_artist.get_listener_count()

		print artist_name + ": " + str(artist.listeners) + " listeners"

def save_stats(artists, filename):
	stats = {}

	for artist_name, artist in artists.items():
		album_stats = {}
		for album in artist.albums.values():
			album_stats[album.name] = album.scrobbles

		stats[artist_name] = (artist.scrobbles, artist.listeners, album_stats)

	f = file(filename, "w")
	pickle.dump(stats, f)
	f.close()

def load_stats(artists, filename):
	f = file(filename, "r")
	stats = pickle.load(f)
	f.close()

	for artist_name, (scrobbles, listeners, album_stats) in stats.items():
		try:
			artists[artist_name].scrobbles = scrobbles
			artists[artist_name].listeners = listeners

			for name, scrobbles in album_stats.items():
				artists[artist_name].albums[name].scrobbles = scrobbles
		except KeyError:
			print artist_name + " no longer in library"

def normalize_stats(artists):
	for artist in artists.values():
		for album in artist.albums.values():
			num_tracks = len(album.songs)
			album.times_listened = album.scrobbles / float(num_tracks)
		
network = pylast.LastFMNetwork(api_key = API_KEY, api_secret = API_SECRET)

mpd = mpd.MPDClient()
mpd.connect("127.0.0.1", 6600)
songs = mpd.listallinfo()

artists = create_artist_list(songs, DIRECTORY, SUB_DIRECTORY, True)
genres = create_genre_list(artists)


#fetch_stats(artists, network)
#save_stats(artists, "stats.bin")

load_stats(artists, "stats.bin")

normalize_stats(artists)

write_html(genres)

#tag_all(songs, network, subdir=SUB_DIRECTORY, translate=TRANSLATE_TAGS, whitelist=TAG_WHITELIST, min_weight=TAG_MIN_WEIGHT)
