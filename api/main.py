from flask import Flask, abort, request, jsonify
from flask_cors import CORS
import os, json, requests
from dotenv import load_dotenv
load_dotenv()

from appwrite.client import Client
from appwrite.services.databases import Databases
from appwrite.query import Query
from appwrite.services.users import Users

from argon2 import PasswordHasher
ph = PasswordHasher()

from cryptography.fernet import Fernet
import base64

client = (Client()
    .set_endpoint(f'{os.environ["APPWRITE_HOST"]}/v1')
    .set_project(os.environ['APPWRITE_ID'])
    .set_key(os.environ['APPWRITE_KEY']))
db = Databases(client)
users = Users(client)

app = Flask(__name__)
CORS(app)

def get_all_docs(data, collection, queries=[]):
    docs = []
    haslimit = False
    for query in queries:
        print(query)
        if query.startswith("limit"):
            print(int(query.split("limit(")[1].split(")")[0]))
            if int(query.split("limit(")[1].split(")")[0]) <= 100: print("true"); haslimit = True

    if not haslimit:
        queries.append(Query.limit(100))
        querylength = len(queries)
        while True:
            if docs:
                queries.append(Query.cursorAfter(docs[-1]['$id']))
            try:
                results = db.list_documents(data, collection, queries=queries)
            except: return docs
            if len(results['documents']) == 0:
                break
            results = results['documents']
            docs += results
            print(data, collection, len(docs))
            if len(queries) != querylength:
                queries.pop()
    else:
        return db.list_documents(data, collection, queries=queries)['documents']
    return docs

@app.get('/hello')
def hello():
    allusers = users.list()
    print(allusers)
    return jsonify({"message": "Hello world!"})


@app.route("/api/login", methods=['POST'])
def login():
    if not request.json or not 'username' in request.json or not 'password' in request.json:
        return jsonify({'error': 'invalid request'}), 400
    username = request.json['username']
    password = request.json['password']

    print("Logging in")
    print(username, password)

    allusers = users.list(queries=[Query.equal('name', username)])['users']
    if len(allusers) == 0:
        sessid = users.create('unique()', name=username, password=password)['$id']
        return jsonify({'sessid': sessid}), 201

    user = allusers[0]
    try:
        ph.verify(user['password'], password)
    except:
        return jsonify({'error': 'invalid password'}), 403

    sessid = user['$id']
    return jsonify({'sessid': sessid}), 201


# HeartRate, Speed

from iso8601 import parse_date

@app.route("/api/sync/<method>", methods=['POST'])
def sync(method):
    if method == "Speed":
        origin = request.json["data"]["metadata"]["dataOrigin"]
        start_time = parse_date(request.json.get("data", {})["startTime"])
        end_time = parse_date(request.json.get("data", {})["endTime"])

        # timedelta:
        duration = end_time - start_time

        speed_m_s = request.json["data"]["samples"][0]["speed"]["inMetersPerSecond"]

        if origin != "com.google.android.apps.fitness":
            print("Different origin for speed", origin)

        print("___SYNC___", method, start_time, end_time - start_time, speed_m_s)
        # ___SYNC___ Speed 2023-08-26 14:23:17.390000+00:00 com.google.android.apps.fitness

    method = method[0].lower() + method[1:]
    if not "userid" in request.json:
        return jsonify({'error': 'no user id provided'}), 400
    if not method:
        return jsonify({'error': 'no method provided'}), 400
    if not "data" in request.json:
        return jsonify({'error': 'no data provided'}), 400

    userid = request.json['userid']
    user = users.get(userid)
    hashed_password = user['password']
    key = base64.urlsafe_b64encode(hashed_password.encode("utf-8").ljust(32)[:32])
    fernet = Fernet(key)

    data = request.json['data']

    if type(data) != list:
        data = [data]
    # print(method, len(data))

    # return jsonify({'success': True}), 200

    try:
        dbid = db.get(userid)['$id']
    except:
        try:
            dbid = db.create(userid, userid)['$id']
        except:
            try:
                dbid = db.list(queries=[Query.equal('name', userid)])['databases'][0]['$id']
            except:
                requests.post("http://localhost:6644/api/sync/"+method, json=request.json)

    # print(dbid)
    try:
        collectionid = db.get_collection(dbid, method)['$id']
    except:
        collectionid = db.create_collection(dbid, method, method, [], False)['$id']
        # print(collectionid)
        db.create_string_attribute(dbid, collectionid, "id", "99", True, array=False)
        db.create_string_attribute(dbid, collectionid, "data", "9999999", True, array=False)
        db.create_string_attribute(dbid, collectionid, "app", "999", True, array=False)
        db.create_datetime_attribute(dbid, collectionid, "start", False, array=False)
        db.create_datetime_attribute(dbid, collectionid, "end", False, array=False)

    print(dbid, collectionid)

    for item in data:
        # print(item)
        itemid = item['metadata']['id']
        dataObj = {}
        for k, v in item.items():
            print("iterating through items")
            if k != "metadata" and k != "time" and k != "startTime" and k != "endTime":
                dataObj[k] = v

        if "time" in item:
            starttime = item['time']
            endtime = None
        else:
            starttime = item['startTime']
            endtime = item['endTime']

        toencrypt = json.dumps(dataObj).encode()
        encrypted = fernet.encrypt(toencrypt).decode()

        # fernet.decrypt(encrypted.encode()).decode()

        # print(starttime, endtime)

        try:
            r = db.list_documents(dbid, collectionid, queries=[Query.equal("id", itemid)])
        except:
            r = {'total': 0}

        if r['total'] > 0:
            print("updating")
            db.update_document(dbid, collectionid, itemid, {"id": itemid, 'data': encrypted, "app": item['metadata']['dataOrigin'], "start": starttime, "end": endtime})
        else:
            print("creating")
            try: db.create_document(dbid, collectionid, itemid, {"id": itemid, 'data': encrypted, "app": item['metadata']['dataOrigin'], "start": starttime, "end": endtime})
            except: pass

    return jsonify({'success': True}), 200

@app.route("/api/fetch/<method>", methods=['POST'])
def fetch(method):
    raise Exception("Disabled temporarily")
    if not "userid" in request.json:
        return jsonify({'error': 'no user id provided'}), 400
    if not method:
        return jsonify({'error': 'no method provided'}), 400

    userid = request.json['userid']
    user = users.get(userid)
    hashed_password = user['password']
    key = base64.urlsafe_b64encode(hashed_password.encode("utf-8").ljust(32)[:32])
    fernet = Fernet(key)

    if not "queries" in request.json:
        queries = []
    else:
        queries = request.json['queries']

    try:
        dbid = db.get(userid)['$id']
    except:
        return jsonify({'error': 'no database found for user'}), 404

    try:
        collectionid = db.get_collection(dbid, method)['$id']
    except:
        return jsonify({'error': 'no collection found for user'}), 404

    docs = get_all_docs(dbid, collectionid, queries=queries)
    for doc in docs:
        doc['data'] = json.loads(fernet.decrypt(doc['data'].encode()).decode())
    return jsonify(docs), 200

app.run(host=os.environ.get('HOST', '0.0.0.0'), port=os.environ.get('PORT', 6644), debug=os.environ.get('DEBUG', False))
