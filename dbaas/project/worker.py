from datetime import datetime
import json
import csv
import sys
import pymongo
import pika
import threading
from time import time




def dbState(collection_name):
	try:
		myclient = pymongo.MongoClient('mongodb://0.0.0.0:27017/')
	except:
		print("dbstate not working")
		return False
	db = myclient["RideShare"]
	collection = db[collection_name]
	return collection


def Add_area():
	myclient = pymongo.MongoClient('mongodb://0.0.0.0:27017/')
	db = myclient["RideShare"]
	collection = db["Area"]
	with open(r"AreaNameEnum.csv","r") as f:
		readCSV = list(csv.DictReader(f))
		for i in range(0, len(readCSV)):
			readCSV[i]['_id'] = int(readCSV[i]['_id'])
			readCSV[i]['Area No'] = int(readCSV[i]['Area No'])
		collection.insert_many(readCSV)


def get_upcoming_rides(args):
	source, destination = args.split(",")
	message = []
	collection = dbState('Rides')
	for rides in collection.find({"source":source,"destination":destination},{"_id":1,"created_by":1,"timestamp":1}):
		if datetime.strptime(datetime.now().strftime("%d-%m-%Y:%S-%M-%H"),"%d-%m-%Y:%S-%M-%H") < datetime.strptime(rides["timestamp"],"%d-%m-%Y:%S-%M-%H"):
			rides = {
				"rideId": rides["_id"],
				"username": rides["created_by"],
				"timestamp":rides["timestamp"]
			}
			message.append(rides)
	return json.dumps({"message":message}).encode()


def entry_exists(args):
	collection_name, field, val = args.split(",")
	collection = dbState(collection_name)
	try:
		val = int(val)
	except:
		val = str(val)
	data = {field: val}
	return json.dumps({"count":collection.count_documents(data)}).encode()


def get_ride_details(args):
	id = args
	collection = dbState('Rides')
	return json.dumps(collection.find_one({'_id':int(id)})).encode()

def read_request_count_ride():
	collection = dbState("RideCount")
	count = collection.find_one({"_id" : "request"})["count"]
	return json.dumps({"count":count}).encode()


def read_ride_count():
	collection = dbState("RideCount")
	count = collection.find_one({"_id" : "ride"})["count"]
	return json.dumps({"count":count}).encode()


def create_entry(body):
	collection = dbState(body["collection"])
	data = body["data"]
	if collection.count_documents({"_id":"Last_Id"}) == 0:
		collection.insert_one({"_id":"Last_Id","Last_Id":0})
	Last_Id = collection.find_one({"_id":"Last_Id"})["Last_Id"] + 1
	data["_id"] = Last_Id
	collection.insert_one(data)
	collection.update_one({"_id":"Last_Id" }, {"$set" : {"Last_Id":Last_Id}})


def delete_entry(body):
	collection = dbState(body["collection"])
	collection.delete_one(body["data"])


def update_ride(body):
	collection = dbState('Rides')
	message = collection.find_one({"_id":body["id"]})
	message['users'].append(body["username"])
	collection.update_one({"_id":body["id"]}, {"$set" : {"users":message["users"]}})


def reset_request_count_ride():
	collection = dbState("RideCount")
	collection.update_one({'_id': "request"}, {'$set': {'count': 0}})


def add_request_count_ride():
	collection = dbState("RideCount")
	collection.update_one({'_id': "request"}, {'$inc': {'count': 1}})


def add_ride_count():
	collection = dbState("RideCount")
	collection.update_one({'_id': "ride"}, {'$inc': {'count': 1}})


def read_all_users():
	collection = dbState('Users')
	if(collection.count_documents({"_id": {'$gte': 1}})):
		users = collection.find()
		user_names = []
		count = 0
		for i in users:
			if(count > 0):
				user_names.append(i['username'])
			count += 1
		return json.dumps({"readall":user_names}).encode()
	else:
		return "0".encode()

def read_request_count_user():
	collection = dbState("UserCount")
	count = collection.find_one({"_id" : 0})["count"]
	return json.dumps({"count":count}).encode()


def delete_all(body):
	collection = dbState(body["collection"])
	collection.remove({})


def reset_request_count_user():
	collection = dbState("UserCount")
	collection.update_one({'_id': 0}, {'$set': {'count': 0}})


def add_request_count_user():
	collection = dbState("UserCount")
	collection.update_one({'_id': 0}, {'$inc': {'count': 1}})


def db_init():
	client = pymongo.MongoClient('mongodb://0.0.0.0:27017')
	dbnames = client.list_database_names()
	if "RideShare" in dbnames:
		db = client["RideShare"]
		db["Rides"].drop()
		db["RideCount"].drop()
		db["Area"].drop()
		db["Users"].drop()
		db["UserCount"].drop()
	Add_area()

	collection = dbState("RideCount")
	collection.insert_one({"_id" : "ride", "count" : 0})
	collection.insert_one({"_id" : "request", "count" : 0})

	collection = dbState("UserCount")
	collection.insert_one({"_id" : 0, "count" : 0})

	collection = dbState("syncQ")
	collection.insert_one({"_id" : "last_id", "value":0})

	print("db init done")


def on_read_request(ch, method, props, body):
	body = body.decode()
	func_name, args = body.split(":")
	print("Read request received for " + func_name)

	if(func_name == "get_upcoming_rides"):
		response = get_upcoming_rides(args)
	if(func_name == "entry_exists"):
		response = entry_exists(args)
	if(func_name == "get_ride_details"):
		response = get_ride_details(args)
	if(func_name == "read_request_count_ride"):
		response = read_request_count_ride()
	if(func_name == "read_ride_count"):
		response = read_ride_count()
	if(func_name == "read_all_users"):
		response = read_all_users()
	if(func_name == "read_request_count_user"):
		response = read_request_count_user()

	ch.basic_publish(
		exchange='',
		routing_key=props.reply_to,
		properties=pika.BasicProperties(correlation_id = props.correlation_id),
		body=response
	)
	ch.basic_ack(delivery_tag=method.delivery_tag)


def on_write_request(ch, method, props, body):
	decoded_body = json.loads(body.decode())
	func_name = decoded_body["func"]
	print("Write request received for " + func_name)

	if(func_name != "sync_command"):
		collection = dbState("syncQ")
		collection.update_one({"_id":"last_id" }, {"$inc" : {"value":1}})
		last_id = collection.find_one({"_id":"last_id" })["value"]
		collection.insert_one({"_id" : last_id, "data":decoded_body})
		sync_data = json.dumps({"_id" : last_id, "data":decoded_body}).encode()

		if(func_name == "create_entry"):
			create_entry(decoded_body, )
		if(func_name == "delete_entry"):
			delete_entry(decoded_body, )
		if(func_name == "update_ride"):
			update_ride(decoded_body, )
		if(func_name == "delete_all"):
			delete_all(decoded_body, )
		if(func_name == "reset_request_count_ride"):
			reset_request_count_ride()
		if(func_name == "add_request_count_ride"):
			add_request_count_ride()
		if(func_name == "add_ride_count"):
			add_ride_count()
		if(func_name == "reset_request_count_user"):
			reset_request_count_user()
		if(func_name == "add_request_count_user"):
			add_request_count_user()

		ch.basic_publish(
			exchange='syncQ',
			routing_key='',
			body=sync_data
		)
	elif(func_name == "sync_command"):
		collection = dbState("syncQ")
		commands = collection.find({"_id":{"$gte" : 0}})
		for i in commands:
			i = json.dumps(i).encode()
			ch.basic_publish(
				exchange="syncQ",
				routing_key="",
				body=i
			)
		print("done serving sync command")
	ch.basic_ack(delivery_tag=method.delivery_tag)


def on_sync_request(ch, method, props, body):
	decoded_body = json.loads(body.decode())
	latest_id = decoded_body["_id"]
	data = decoded_body["data"]
	func_name = data["func"]

	print("Sync request received for " + func_name)

	collection = dbState("syncQ")
	if(collection.find_one({"_id" : "last_id"})["value"] < latest_id):
		collection.update_one({"_id" : "last_id"}, {"$inc" : {"value":1}})
		collection.insert_one(decoded_body)

		if(func_name == "create_entry"):
			create_entry(data)
		if(func_name == "delete_entry"):
			delete_entry(data)
		if(func_name == "update_ride"):
			update_ride(data)
		if(func_name == "delete_all"):
			delete_all(data)
		if(func_name == "reset_request_count_ride"):
			reset_request_count_ride()
		if(func_name == "add_request_count_ride"):
			add_request_count_ride()
		if(func_name == "add_ride_count"):
			add_ride_count()
		if(func_name == "reset_request_count_user"):
			reset_request_count_user()
		if(func_name == "add_request_count_user"):
			add_request_count_user()


if __name__ == '__main__':
	connection = pika.BlockingConnection(pika.ConnectionParameters(host='rmq', heartbeat=0))
	designation = int(sys.argv[1])
	print("Ready for receiving requests.")
	if(designation == 1):
		print("master mode")
		db_init()
		channel_write = connection.channel()
		channel_write.exchange_declare(exchange='syncQ', exchange_type='fanout')
		channel_write.queue_declare(queue="writeQ")
		channel_write.basic_qos(prefetch_count=1)
		channel_write.basic_consume(queue="writeQ", on_message_callback=on_write_request)
		channel_write.start_consuming()
	elif(designation == 0):
		print("slave mode")
		db_init()

		channel = connection.channel()
		channel.queue_declare(queue='readQ')
		channel.basic_qos(prefetch_count=1)
		channel.basic_consume(queue='readQ', on_message_callback=on_read_request)

		channel.exchange_declare(exchange="syncQ", exchange_type="fanout")
		result = channel.queue_declare(queue='', exclusive=True)
		queue_name = result.method.queue
		channel.queue_bind(exchange='syncQ', queue=queue_name)
		channel.basic_consume(queue=queue_name, on_message_callback=on_sync_request, auto_ack=True)


		# t1 = threading.Thread(target=channel.start_consuming)
		# t1.start()
		print("sync command sent ")
		params = json.dumps({"func":"sync_command"}).encode()
		channel.basic_publish(
			exchange="",
			routing_key="writeQ",
			body=json.dumps({"func":"sync_command"}).encode()
		)
		channel.start_consuming()		
