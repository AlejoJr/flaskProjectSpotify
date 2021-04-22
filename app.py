from flask import Flask, url_for, session, request, redirect, render_template
import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import json
import time
import pandas as pd
from flaskext.mysql import MySQL
import pymysql
import requests
import statistics
from google_trans_new import google_translator
from afinn import Afinn, afinn

db = pymysql.connect(
    host='localhost',
    user='root',
    password='d1n4m1kjr',
    db='dbflaskspotify',
    autocommit=True
)

app = Flask(__name__)
api = MySQL(app)

app.secret_key = 'SOMETHING-RANDOM'
app.config['SESSION_COOKIE_NAME'] = 'spotify-login-session'

cursor = db.cursor()

@app.route('/', methods=["GET"])
def index():
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    nameMail = request.form['email']
    cursor.execute('INSERT INTO email (email) VALUES (%s)', (nameMail))
    cursor.connection.commit()
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    print(auth_url)
    return redirect(auth_url)


@app.route('/authorize')
def authorize():
    sp_oauth = create_spotify_oauth()
    session.clear()
    code = request.args.get('code')
    token_info = sp_oauth.get_access_token(code)
    session["token_info"] = token_info
    return redirect("/getTracks")


@app.route('/logout')
def logout():
    for key in list(session.keys()):
        session.pop(key)
    return redirect('/login')


@app.route('/getTracks')
def get_all_tracks():
    cursor.execute("SELECT email FROM email ORDER BY id desc limit 1;")
    mail = cursor.fetchone()

    session['token_info'], authorized = get_token()
    session.modified = True
    if not authorized:
        return redirect('/login')
    sp = spotipy.Spotify(auth=session.get('token_info').get('access_token'))
    results = []
    iter = 0
    while True:
        offset = iter * 50
        iter += 1
        curGroup = sp.current_user_saved_tracks(limit=50, offset=offset)['items']
        for idx, item in enumerate(curGroup):
            track = item['track']
            song = track['name']
            artist = track['artists'][0]['name']

            query_string = "SELECT name FROM songs WHERE email = %s and name = %s;"
            cursor.execute(query_string, (mail,song))
            data = cursor.fetchall()
            if len(data) == 0:
                cursor.execute('INSERT INTO songs (name,artist,email) VALUES (%s,%s,%s)', (song,artist,mail))
                cursor.connection.commit()
            val = track['name'] + " - " + track['artists'][0]['name']
            results += [val]
        if (len(curGroup) < 50):
            break

    df = pd.DataFrame(results, columns=["song names"])
    df.to_csv('songs2.csv', index=False)
    return redirect(url_for('show_table_songs', email=mail))

@app.route('/tablesongs')
def show_table_songs():
    mail = request.args['email']
    query_string = "SELECT * FROM songs WHERE email= %s;"
    cursor.execute(query_string, (mail,))
    data = cursor.fetchall()
    return render_template('songs.html', songs=data, user=mail)

@app.route('/songsAnalyze', methods=['POST'])
def show_table_songs_analyze():
    mail = request.args['email']
    query_string = "SELECT * FROM songs WHERE email= %s;"
    cursor.execute(query_string, (mail,))
    data = cursor.fetchall()
    for song in data:
        idSong = song[0]
        nameSong = song[1]
        artist = song[2]
        finalScore = fetchlyrics(nameSong, artist, idSong)

        if finalScore != '':
            query_string = "UPDATE songs SET afinn=%s WHERE name=%s AND artist=%s AND email=%s"
            cursor.execute(query_string, (finalScore, nameSong, artist, mail))

    query_string = "SELECT * FROM songs WHERE email= %s AND afinn is not null;"
    cursor.execute(query_string, (mail,))
    data = cursor.fetchall()

    listScores = []
    for song in data:
        score = song[4]
        listScores.append(score)

    mean = statistics.mean(listScores)
    mean = "{0:.2f}".format(mean)

    sentiment = ''
    mean = float(mean)

    if -4 <= mean <= -1:
        sentiment = 'Desanimado'
    elif -8 <= mean <= -4:
        sentiment = 'Triste'
    elif mean < -8:
        sentiment = 'Melancólico'
    elif -1 <= mean <= 1:
        sentiment = 'Normal'
    elif 1 <= mean <= 4:
        sentiment = 'Felíz'
    elif 4 <= mean <= 8:
        sentiment = 'Alegre'
    elif mean > 8:
        sentiment = 'Fenomenal'

    return render_template('afinn.html', songs=data, user=mail,mean= mean, sentiment=sentiment)

#Obtener letra de cancion
def fetchlyrics(songTitle,artist,idSong):
    url = 'https://api.lyrics.ovh/v1/' + artist + '/' + songTitle
    response = requests.get(url)
    json_data = json.loads(response.content)
    if 'lyrics' in json_data:
        lyrics = json_data['lyrics']
        query_string = "UPDATE songs SET lyrics=%s WHERE id=%s"
        cursor.execute(query_string, (lyrics, idSong))
        finalScore = calculateAfinnScore(lyrics)
    else:
        return ''
    return finalScore

def calculateAfinnScore(lyrics):
    afinn = Afinn()
    translator = google_translator()

    translation = translator.translate(text=lyrics, lang_tgt='en', lang_src='auto')
    resultAfinn = afinn.score(translation)

    # Calculate word cound of lyric
    word_count = len(translation.split())

    # Calculate comparative score
    comparative_score = resultAfinn / word_count

    finalScore = "{0:.2f}".format(comparative_score * 100)

    return finalScore

@app.route('/songsLyrics', methods=['GET', 'POST'])
def showLyrics():
    idSong = request.args['idSong']
    nameSong = request.args['nameSong']
    mail = request.args['mail']
    query_string = "SELECT lyrics FROM songs WHERE id= %s;"
    cursor.execute(query_string, (idSong,))
    data = cursor.fetchone()
    text = data[0].split('\n')
    return render_template('showLyrics.html', lyrics=text, nameSong=nameSong, mail=mail)

# Checks to see if token is valid and gets a new token if not
def get_token():
    token_valid = False
    token_info = session.get("token_info", {})

    # Checking if the session already has a token stored
    if not (session.get('token_info', False)):
        token_valid = False
        return token_info, token_valid

    # Checking if token has expired
    now = int(time.time())
    is_token_expired = session.get('token_info').get('expires_at') - now < 60

    # Refreshing token if it has expired
    if (is_token_expired):
        sp_oauth = create_spotify_oauth()
        token_info = sp_oauth.refresh_access_token(session.get('token_info').get('refresh_token'))

    token_valid = True
    return token_info, token_valid


def create_spotify_oauth():
    return SpotifyOAuth(
        client_id="97afcf6048794abea474504cf56c2807",
        client_secret="1df02fd3a5444389b137e05868cdc0fb",
        redirect_uri=url_for('authorize', _external=True),
        scope="user-library-read")


if os.path.exists(".cache"):
    os.remove(".cache")

if __name__ == '__main__':
    app.run(debug=True)
