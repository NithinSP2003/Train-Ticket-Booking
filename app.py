from flask import Flask, request, render_template, redirect, url_for,flash,session, jsonify, send_file
import pymysql, io, time
from datetime import datetime, timedelta, date
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import random, string
from fpdf import FPDF
import pdfkit

conn = pymysql.connect(
    host="mydb.chss26eaa57v.ap-south-1.rds.amazonaws.com",       
    user="admin",
    password="trainbooking",
    database="Train_Booking",
    port=3306,  
)


app = Flask(__name__)
app.secret_key = 'your_secret_key'

CLASS_LABELS = {
    '1A': 'AC First Class',
    '2A': 'AC 2 Tier',
    '3A': 'AC 3 Tier',
    'SL': 'Sleeper',
    'CC': 'AC Chair Car',
    '2S': 'Second Seating',
    'GN': 'General'
}

station_name = [
    "Agra", "Ambala", "Asansol", "Bangalore", "Bhopal", "Chennai", 
    "Dindigul", "Erode", "Firozpur", "Gaya", "Gwalior", "Howrah", 
    "Jhansi", "Kanyakumari", "Karur", "Kota", "Ludhiana", "Madurai", 
    "Manamadurai", "Mughalsarai", "Mumbai", "Nagpur", "New Delhi", 
    "Rameswaram", "Salem", "Surat", "Tirunelveli", "Trichy", "Vadodara", 
    "Villupuram"
]

# ---> Booking Page <---

@app.route('/get_availability')
def get_availability():
    train_number = request.args.get('train_number')
    class_code = request.args.get('class_code')
 
    results = []
 
    try:
        with conn.cursor() as cursor:
            query = """
                SELECT travel_date, available_count, rac_count, wl_count
                FROM availability
                WHERE train_number = %s AND class_code = %s
                ORDER BY travel_date
                LIMIT 5
            """
            cursor.execute(query, (train_number, class_code))
            rows = cursor.fetchall()
    
            if rows:
                for row in rows:
                    travel_date, available, rac, wl = row
 
                    if available > 0:
                        availability_status = f"Available: {available}"
                    elif rac > 0:
                        availability_status = f"RAC: {rac}"
                    else:
                        availability_status = f"WL: {wl}"
 
                    results.append({
                        "date": travel_date.strftime('%a, %d %b'),
                        "availability": availability_status
                    })
            else:
                print("No data found for this query.")
 
    except Exception as e:
        print(f"Error during database query: {e}")
 
    return jsonify(results)

def calculate_duration(departure_time, arrival_time):
    fmt = '%H:%M:%S'
    try:
        dep = datetime.strptime(str(departure_time), fmt)
        arr = datetime.strptime(str(arrival_time), fmt)
    except ValueError:
        return "—:—"

    if arr < dep:
        arr += timedelta(days=1)

    duration = arr - dep
    hours, remainder = divmod(duration.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h {minutes}m"

def calculate_fare(train_no, from_station, to_station, class_code):
    with conn.cursor() as cursor:
        # Get distances
        dist_query = """
            SELECT station_name, distance_from_start
            FROM station_distances
            WHERE train_number = %s
        """
        cursor.execute(dist_query, (train_no,))
        distances = {row[0]: row[1] for row in cursor.fetchall()}

        if from_station not in distances or to_station not in distances:
            print("Invalid stations:", from_station, to_station)
            return None, None  # Invalid stations

        distance = abs(distances[to_station] - distances[from_station])

        # Get fare rate
        fare_query = "SELECT rate_per_km FROM fare_rates WHERE class_code = %s"
        cursor.execute(fare_query, (class_code,))
        rate_row = cursor.fetchone()

        if not rate_row:
            print("Invalid class code:", class_code)
            return None, None

        rate = rate_row[0]
        fare = distance * rate
        print("Calculated fare:", fare, "for distance:", distance)
        return round(fare, 2), distance

@app.route('/cal_fare',methods=['POST'])
def get_fare():
    data = request.get_json()
    train_number = data['trainNumber']
    from_station = data['from']
    to_station = data['to']
    class_code = data['classCode']

    fare,distance = calculate_fare(train_number, from_station, to_station, class_code)

    if fare is None:
            return jsonify({'error': 'Invalid stations or class code'}), 400

    
    return jsonify({'fare': fare})


def generate_pnr():
    date_code = datetime.now().strftime("%d%m")
    random_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{date_code}{random_code}"

def preference(pref, L, pref_type):
    if pref_type == 'seating':  # GN or 2S
        options = ['Window', 'Middle', 'Aisle']
    else:  # Sleeper or AC
        options = ['Lower', 'Middle', 'Upper', 'Side Lower', 'Side Upper']
 
    if pref in options:
        lst = [options.index(pref)] + [i for i in range(len(options)) if i != options.index(pref)]
    else:
        lst = list(range(len(options)))
    print(lst)
 
    for i in lst:
        if L[i] > 0:
            L[i] -= 1
            return options[i]
 
    if L[-1] > 0:
        L[-1] -= 1
        return 'rac'
 
    return 'waiting'

@app.route('/')
def index():
    today = date.today().isoformat()
    return render_template('index.html', stations=station_name, today=today, class_labels=CLASS_LABELS)

def get_station_and_class(request):
    from_station = request.form.get('from', '').strip() or request.args.get('from', '').strip()
    to_station = request.form.get('to', '').strip() or request.args.get('to', '').strip()
    class_type = request.form.get('class', '').strip() or request.args.get('class', '').strip()
    travel_date = request.form.get('date', '').strip() or request.args.get('date', '').strip()
    return from_station, to_station, class_type,travel_date

@app.route('/ticket-list', methods=['POST', 'GET'])
def search():
    from_station, to_station, class_type, travel_date = get_station_and_class(request)
    session['from'] = from_station
    session['to'] = to_station
    session['date'] = travel_date
    session['class_code'] = class_type
 
    matching_trains = []
 
    with conn.cursor() as cursor:
        query = """
            SELECT DISTINCT
                t.train_number, t.train_name, t.route, t.train_type, t.classes,
                ts1.departure_time, ts2.arrival_time, t.run_days,
                a.travel_date,
                CASE
                    WHEN ts2.arrival_time < ts1.departure_time THEN DATE_ADD(a.travel_date, INTERVAL 1 DAY)
                    ELSE a.travel_date
                END AS arrival_date
            FROM trains t
            JOIN train_schedule ts1 ON t.train_number = ts1.train_number
            JOIN train_schedule ts2 ON t.train_number = ts2.train_number
            JOIN availability a ON t.train_number = a.train_number
            WHERE ts1.station_name = %s
            AND ts2.station_name = %s
            AND a.travel_date = %s
        """
        val = (from_station, to_station, travel_date)
        cursor.execute(query, val)
        trains = cursor.fetchall()
 
        current_time = datetime.now()
 
        for train1 in trains:
            train = {
                'number': train1[0],
                'name': train1[1],
                'route': train1[2],
                'type': train1[3],
                'classes': train1[4],
                'departure_time': train1[5],
                'arrival_time': train1[6],
                'days': train1[7],
                'travel_date': train1[8],
                'arrival_date': train1[9]
            }
 
            route = [station.strip().lower() for station in train['route'].split(',')]
            if from_station.lower() in route and to_station.lower() in route:
                if route.index(from_station.lower()) < route.index(to_station.lower()):
                    if class_type and class_type not in train['classes'].split(','):
                        continue
 
                    if not train['departure_time'] or not train['arrival_time']:
                        continue
 
                    if isinstance(train['departure_time'], timedelta):
                        dep_time = (datetime.min + train['departure_time']).time()
                    else:
                        dep_time = train['departure_time']
 
                    departure_datetime = datetime.combine(train['travel_date'], dep_time)
 
                    if departure_datetime <= current_time + timedelta(hours=1):
                        continue
 
                    train['duration'] = calculate_duration(train['departure_time'], train['arrival_time'])
                    train['journey_date'] = train['travel_date']
                    matching_trains.append(train)
 
    return render_template('train-list.html',
                           trains=matching_trains,
                           from_station=from_station,
                           to_station=to_station,
                           class_type=class_type,
                           class_labels=CLASS_LABELS,
                           station_name=station_name)

@app.route('/ticket-list1', methods=['GET'])
def search_loggedin():
        from_station = request.args.get('from_')
        to_station = request.args.get('to')
        travel_date = request.args.get('date')
        class_type = request.args.get('class_')
        print(from_station, to_station, class_type, travel_date,'search loggedin')
        print('hi')
        matching_trains = []

        with conn.cursor() as cursor:
            query = """
                    SELECT DISTINCT 
                        t.train_number, t.train_name, t.route, t.train_type, t.classes,
                        ts1.departure_time, ts2.arrival_time, t.run_days,
                        a.travel_date,
                    CASE 
                        WHEN ts2.arrival_time < ts1.departure_time THEN DATE_ADD(a.travel_date, INTERVAL 1 DAY)
                        ELSE a.travel_date
                    END AS arrival_date
                    FROM trains t
                    JOIN train_schedule ts1 ON t.train_number = ts1.train_number 
                    JOIN train_schedule ts2 ON t.train_number = ts2.train_number
                    JOIN availability a ON t.train_number = a.train_number
                    WHERE ts1.station_name = %s 
                    AND ts2.station_name = %s 
                    AND a.travel_date = %s;
                    """
            val = (from_station, to_station, travel_date)
            cursor.execute(query, val)
            trains = cursor.fetchall()
            for train1 in trains:
                train = {
                    'number': train1[0],
                    'name': train1[1],
                    'route': train1[2],
                    'type': train1[3],
                    'classes': train1[4],
                    'departure_time': train1[5],
                    'arrival_time': train1[6],
                    'days': train1[7],
                    'travel_date': train1[8]
                }
                route = [station.strip().lower() for station in train['route'].split(',')]
                if from_station.lower() in route and to_station.lower() in route:
                    if route.index(from_station.lower()) < route.index(to_station.lower()):
                        if class_type and class_type not in train['classes'].split(','):
                            continue

                        # Skip trains with missing times
                        if not train['departure_time'] or not train['arrival_time']:
                            continue

                        train['duration'] = calculate_duration(train['departure_time'], train['arrival_time'])
                        train['journey_date'] = train['travel_date']
                        matching_trains.append(train)

        return render_template('train-list.html',
                            trains=matching_trains,
                            from_station=from_station,
                            to_station=to_station,
                            class_type=class_type,
                            class_labels=CLASS_LABELS)

@app.route('/logout')
def logout():
    session.pop('user_logged_in', None)
    session.clear()
    return redirect(url_for('index'))

@app.route('/summary', methods=['POST'])
def summary():
    pnr = generate_pnr()
    
    passengers = session.get('passengers', [])
    train_no = session.get('train_number',[])
    class_code = session.get('class_code', [])
    date = session.get('date')
    total_fare=session.get('total_fare')

 
    updated_passengers = []
 
    # Determine if class uses seating or sleeper-type preference
    if class_code in ['2S', 'GN']:
        berth_types = ['Window', 'Middle', 'Aisle']
        pref_type = 'seating'
    else:
        berth_types = ['Lower', 'Middle', 'Upper', 'Side Lower', 'Side Upper']
        pref_type = 'sleeper'
 
    seat_counts = {bt: 0 for bt in berth_types}
    print("seat_count",seat_counts)
    seat_counts['rac'] = 6
    print("seat_count",seat_counts)

 
    cursor = conn.cursor()
    query = """
            SELECT berth_type, COUNT(*) FROM seat_berth2
            WHERE train_no = %s AND class_code = %s AND ticket_status = 'Available'
            GROUP BY berth_type
        """
    cursor.execute(query, (train_no, class_code))
    for row in cursor.fetchall():
        berth_type, count = row
        if berth_type in seat_counts:
            seat_counts[berth_type] = count
 
    seat_count_list = [seat_counts[bt] for bt in berth_types] + [seat_counts['rac']]
    print('seat_count_list', seat_count_list)
    for p in passengers:
        pref_code = p['berth']
        allotted_berth = preference(pref_code, seat_count_list, pref_type)
 
        if allotted_berth != 'waiting' and allotted_berth != 'rac':
                seat_query = """
                    SELECT seat_number FROM seat_berth2
                    WHERE train_no = %s AND class_code = %s AND berth_type = %s AND ticket_status = 'Available' AND travel_date = %s
                    LIMIT 1
                """
                cursor.execute(seat_query, (train_no, class_code, allotted_berth,date,))
                seat_row = cursor.fetchone()
 
                if seat_row:
                    seat_no = seat_row[0]
                    update_query = """
                        UPDATE seat_berth2
                        SET ticket_status = 'Booked'
                        WHERE train_no = %s AND class_code = %s AND seat_number = %s AND travel_date = %s
                    """
                    cursor.execute(update_query, (train_no, class_code, seat_no,date,))
                    booking_status = "Confirmed"
                else:
                    booking_status = "Waiting"
                    seat_no = None
        else:
                booking_status = "Waiting"
                seat_no = None
 
        p['berth_allotted'] = allotted_berth
        p['seat_no'] = seat_no
        p['booking_status'] = booking_status
 
        insert_query = """
                INSERT INTO passenger (passenger_name, age, gender, berth_preference, nationality, pnr_number, berth_allotted, seat_no,user_id,train_number,from_station, to_station, class, travel_date, booking_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        cursor.execute(insert_query, (
                p['name'], int(p['age']), p['gender'], p['berth'], p['nationality'],
                pnr, p['berth_allotted'], p['seat_no'], session['user_id'], session['train_number'],
                session['from'],session['to'],session['class_code'], session['date'],p['booking_status']
            ))
 
        updated_passengers.append(p)

        try:
                    cursor.execute("""
                                   select distinct t.train_number, t.train_name,t.route, t.train_type, t.classes,
                            ts1.departure_time, ts2.arrival_time, t.run_days, a.travel_date,ts1.station_name,ts2.station_name
                            from trains t
                            join train_schedule ts1 on t.train_number = ts1.train_number 
                            join train_schedule ts2 on t.train_number = ts2 .train_number
                            join availability a on t.train_number = a.train_number
                            where ts1.station_name = %s and ts2.station_name = %s and a.travel_date = %s and t.train_number = %s
                        """, (session['from'], session['to'], session['date'], session['train_number'],))
                    row = cursor.fetchone()

                    if not row:
                        return "Train not found", 404

                    train = {
                        'number': row[0],
                        'name': row[1],
                        'route': row[2],
                        'type': row[3],
                        'classes': row[4],
                        'departure_time': row[5],
                        'arrival_time': row[6],
                        'run_days': row[7],
                        'duration': calculate_duration(row[5], row[6]),
                        'journey_date' :row[8],
                        'from' : row[9],
                        'to' : row[10]
                    }
                    print(train)

        except Exception as e:
                return f"Database error: {e}", 500
 
        cursor.execute(
                """UPDATE availability
                SET available_count = (
                                        SELECT COUNT(*) FROM seat_berth2
                                        WHERE train_no = %s AND class_code = %s 
                                        AND ticket_status = 'Available' AND travel_date = %s
                                    )
                WHERE train_number = %s AND class_code = %s AND travel_date = %s;
                """,(session['train_number'], session['class_code'], session['date'],
                     session['train_number'], session['class_code'], session['date'],))
           
        conn.commit()
    
 
    
    return render_template('summary.html', train=train,pnr=pnr,class_labels=CLASS_LABELS, passengers=updated_passengers, date = session.get('date'), total_fare = session.get('total_fare'),class_code=session['class_code'])

@app.route('/book')
def book():
    
    today = date.today()
    train_number = request.args.get('train')
    session['class_code'] = request.args.get('class')
    status = request.args.get('status')



    today = date.today()

    
   
    if not train_number:
        return "Train number missing", 400

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                            select distinct t.train_number, t.train_name,t.route, t.train_type, t.classes,
                            ts1.departure_time, ts2.arrival_time, t.run_days, a.travel_date,ts1.station_name,ts2.station_name
                            from trains t
                            join train_schedule ts1 on t.train_number = ts1.train_number 
                            join train_schedule ts2 on t.train_number = ts2 .train_number
                            join availability a on t.train_number = a.train_number
                            where ts1.station_name = %s and ts2.station_name = %s and a.travel_date = %s and t.train_number = %s


                        """, (session['from'], session['to'], session['date'], train_number,))
            row = cursor.fetchone()


            if not row:
                return "Train not found", 404

            train = {
                'number': row[0],
                'name': row[1],
                'route': row[2],
                'type': row[3],
                'classes': row[4],
                'departure_time': row[5],
                'arrival_time': row[6],
                'run_days': row[7],
                'duration': calculate_duration(row[5], row[6]),
                'journey_date' : row[8],
                'from' : row[9],
                'to' : row[10]

            }

            session['train_number'] = train['number']

            print("Session Date:", session['date'])
            print("Today:", date.today())

           






    except Exception as e:
        return f"Database error: {e}", 500

    return render_template('passenger-details.html',
                           train=train,
                           class_code=session['class_code'],
                           date=session['date'],
                           class_labels=CLASS_LABELS)

@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    if request.method == 'POST':
        form = request.form
        passengers = {}
 
        for key in form:
            if '-' in key:
                field, num = key.split('-')
                if num not in passengers:
                    passengers[num] = {}
                passengers[num][field] = form[key]

    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                            select distinct t.train_number, t.train_name,t.route, t.train_type, t.classes,
                            ts1.departure_time, ts2.arrival_time, t.run_days, a.travel_date,ts1.station_name,ts2.station_name
                            from trains t
                            join train_schedule ts1 on t.train_number = ts1.train_number 
                            join train_schedule ts2 on t.train_number = ts2 .train_number
                            join availability a on t.train_number = a.train_number
                            where ts1.station_name = %s and ts2.station_name = %s and a.travel_date = %s and t.train_number = %s
                        """, (session['from'], session['to'], session['date'], session['train_number'],))
            row = cursor.fetchone()

            if not row:
                return "Train not found", 404

            train = {
                'number': row[0],
                'name': row[1],
                'route': row[2],
                'type': row[3],
                'classes': row[4],
                'departure_time': row[5],
                'arrival_time': row[6],
                'run_days': row[7],
                'duration': calculate_duration(row[5], row[6]),
                'journey_date' :row[8],
                'from' : row[9],
                'to' : row[10]

            }

    except Exception as e:
        return f"Database error: {e}", 500
 
    session['passengers'] = list(passengers.values())

    total_fare = 0
    fare, distance = calculate_fare(session['train_number'], session['from'], session['to'], session['class_code'])
    session['fare'] = fare
    for p in session['passengers']:
        print(p)
        total_fare += fare
        print(fare)
        session['total_fare'] = total_fare
    return render_template('confirmation.html',fare = session.get('fare'),total_fare=session.get('total_fare'),train=train, date=session['date'] ,passengers=session['passengers'],class_labels=CLASS_LABELS, class_code=session['class_code'])

@app.route('/login', methods=['GET','POST'])
def login_user():
    if not session.get('from'):
        if request.method == 'POST':
            print('1')
            cursor = conn.cursor()
            user_name = request.form['user-name']
            user_password = request.form['user-password']
            sql = "SELECT * FROM users WHERE user_name = %s AND password = %s"
            val = (user_name, user_password)
            cursor.execute(sql, val)
            result = cursor.fetchone()
            if result:
                session['user_id']= result[0]
                session['user_logged_in'] = True
                session['user_name'] = result[1] 
                return redirect(url_for('index'))
            else:
                return "Invalid credentials"
        elif request.method == 'GET':
            print('2')
            return render_template('login.html')
    else:
        if request.method == 'POST':
            print('3')
            cursor = conn.cursor()
            user_name = request.form['user-name']
            user_password = request.form['user-password']
            from_location = session.get('from')
            to_location = session.get('to')
            travel_date = session.get('date')
            class_code = session.get('class_code')
            sql = "SELECT * FROM users WHERE user_name = %s AND password = %s"
            val = (user_name, user_password)
            cursor.execute(sql, val)
            result = cursor.fetchone()
            if result:
                session['user_id']= result[0]
                session['user_logged_in'] = True
                session['user_name'] = result[1] 
                print(from_location)
                print(to_location) 
                print(travel_date)
                print(class_code)
                print(type(travel_date))
                
                return redirect(url_for('search_loggedin', from_=from_location, to=to_location, date=travel_date, class_=class_code))
            else:
                return "Invalid credentials"
        elif request.method == 'GET':
            print('4')
            return render_template('login.html')

@app.route('/signup', methods=['GET','POST'])
def signup_user():
    if request.method == 'POST':
        cursor = conn.cursor()
        user_name = request.form['user-name']
        full_name = request.form['full-name']
        user_email = request.form['user-email']
        user_number = request.form['user-number']
        user_password = request.form['user-password']
        password_confirm = request.form['user-password-val']

        sql = "INSERT INTO users (user_name, full_name, email, number,password) VALUES (%s, %s, %s, %s, %s)"
        val = (user_name, full_name, user_email,user_number,user_password)
        cursor.execute(sql, val)
        conn.commit()
        return redirect(url_for('login_user'))
    
    elif request.method == 'GET':
        return render_template('signup.html')


@app.route('/get_route/<train_number>')
def get_route(train_number):
    station_coords = {
        'New Delhi': {'lat': 28.6139, 'lon': 77.2090, 'name': 'New Delhi'},
        'Agra': {'lat': 27.1767, 'lon': 78.0081, 'name': 'Agra'},
        'Gwalior': {'lat': 26.2183, 'lon': 78.1828, 'name': 'Gwalior'},
        'Jhansi': {'lat': 25.4484, 'lon': 78.5685, 'name': 'Jhansi'},
        'Bhopal': {'lat': 23.2599, 'lon': 77.4126, 'name': 'Bhopal'},
        'Firozpur': {'lat': 30.9255, 'lon': 74.6131, 'name': 'Firozpur'},
        'Ludhiana': {'lat': 30.9010, 'lon': 75.8573, 'name': 'Ludhiana'},
        'Nagpur': {'lat': 21.1458, 'lon': 79.0882, 'name': 'Nagpur'},
        'Mumbai': {'lat': 19.0760, 'lon': 72.8777, 'name': 'Mumbai'},
        'Howrah': {'lat': 22.5958, 'lon': 88.2636, 'name': 'Howrah'},
        'Asansol': {'lat': 23.6833, 'lon': 86.9667, 'name': 'Asansol'},
        'Gaya': {'lat': 24.7969, 'lon': 85.0000, 'name': 'Gaya'},
        'Mughalsarai': {'lat': 25.2818, 'lon': 83.1197, 'name': 'Mughalsarai'},
        'Ambala': {'lat': 30.3782, 'lon': 76.7767, 'name': 'Ambala'},
        'Amritsar': {'lat': 31.6340, 'lon': 74.8723, 'name': 'Amritsar'},
        'Chennai': {'lat': 13.0827, 'lon': 80.2707, 'name': 'Chennai'},
        'Salem': {'lat': 11.6643, 'lon': 78.1460, 'name': 'Salem'},
        'Karur': {'lat': 10.9576, 'lon': 78.0810, 'name': 'Karur'},
        'Madurai': {'lat': 9.9252, 'lon': 78.1198, 'name': 'Madurai'},
        'Tirunelveli': {'lat': 8.7139, 'lon': 77.7567, 'name': 'Tirunelveli'},
        'Kanyakumari': {'lat': 8.0883, 'lon': 77.5385, 'name': 'Kanyakumari'},
        'Trichy': {'lat': 10.7905, 'lon': 78.7047, 'name': 'Trichy'},
        'Dindigul': {'lat': 10.3673, 'lon': 77.9803, 'name': 'Dindigul'},
        'Villupuram': {'lat': 11.9393, 'lon': 79.4930, 'name': 'Villupuram'},
        'Erode': {'lat': 11.3410, 'lon': 77.7172, 'name': 'Erode'},
        'Bangalore': {'lat': 12.9716, 'lon': 77.5946, 'name': 'Bangalore'},
        'Surat': {'lat': 21.1702, 'lon': 72.8311, 'name': 'Surat'},
        'Vadodara': {'lat': 22.3072, 'lon': 73.1812, 'name': 'Vadodara'},
        'Kota': {'lat': 25.2138, 'lon': 75.8648, 'name': 'Kota'},
        'Manamadurai': {'lat': 9.6928, 'lon': 78.4810, 'name': 'Manamadurai'},
        'Rameswaram': {'lat': 9.2886, 'lon': 79.3174, 'name': 'Rameswaram'},
        # Add others as needed
    }

    cursor = conn.cursor()
    cursor.execute("SELECT route FROM trains WHERE train_number = %s", (train_number,))
    result = cursor.fetchone()
    print(result)

    if not result:
        return jsonify({"error": "Train not found"}), 404
    
    route_str = result[0]
    stations = [s.strip() for s in route_str.split(",")]

    geolocator = Nominatim(user_agent="train_route_mapper_web")
    station_coords = []

    for station in stations:
        try:
            location = geolocator.geocode(station + ", India", timeout=5)
            if location:
                station_coords.append({
                    "name": station,
                    "lat": location.latitude,
                    "lon": location.longitude
                })
        except GeocoderTimedOut:
            continue

        time.sleep(1)
    return jsonify(station_coords)

@app.route('/pnr_enquiry', methods=['GET', 'POST'])
def pnr_enquiry():
    ticket_details = None  
    train_numb = None
    from_station = None
    to_station = None
    class_code = None
    travel_date = None
    pnr_number = None
    booking_status = None
    total_fare=session.get('total_fare')
    fare = session.get('fare')
    if request.method == 'POST':
        pnr_number = request.form['pnr_number']

        if pnr_number:
            cursor = conn.cursor()

            # Fetch the details of passengers for the given PNR number
            cursor.execute("SELECT * FROM passenger WHERE pnr_number = %s", (pnr_number,))
            ticket_details = cursor.fetchall()

            if ticket_details:
                train_numb = ticket_details[0][11]
                from_station = ticket_details[0][12]
                to_station = ticket_details[0][13]
                class_code = ticket_details[0][14]
                travel_date = ticket_details[0][15]
                pnr_number = ticket_details[0][5]
                print(ticket_details[0])
            else:
                flash("No records found for this PNR number.", "danger")
        
        return render_template('pnr-enquiry.html',
                    ticket_details=ticket_details,
                    train_numb=train_numb,
                    from_station=from_station,
                    to_station=to_station,
                    class_code=class_code,
                    travel_date=travel_date,
                    pnr_number=pnr_number,
                    total_fare=session.get('total_fare'),
                    fare = session.get('fare'),
                    passengers = session['passengers'])

    return render_template('pnr-enquiry.html',
                       ticket_details=ticket_details,
                       train_numb=train_numb,
                       from_station=from_station,
                       to_station=to_station,
                       class_code=class_code,
                       travel_date=travel_date,
                       pnr_number=pnr_number,
                       total_fare=session.get('total_fare'),
                       fare = session.get('fare'),
                       passengers = session['passengers'])

from flask import render_template, request, redirect, url_for, flash, session
from datetime import datetime, date

from datetime import datetime

@app.route('/cancel_tickets', methods=['GET', 'POST'])
def cancel_tickets():
    user_id = session['user_id']  # Hardcoded for now; replace with session['user_id'] later
    cursor = conn.cursor()

    if request.method == 'POST':
        selected_ids = request.form.getlist('passenger_ids')
        for pid in selected_ids:
            cursor.execute("SELECT seat_no, train_number FROM passenger WHERE passenger_id = %s", (pid,))
            result = cursor.fetchone()
            if result:
                seat_no = result[0]
                train_number = result[1]
                # Cancel ticket
                cursor.execute("UPDATE passenger SET booking_status = 'Cancelled' WHERE passenger_id = %s", (pid,))
                # Free seat
                cursor.execute("UPDATE seat_berth2 SET ticket_status = 'Available' WHERE seat_number = %s AND train_no = %s", (seat_no, train_number))
        conn.commit()

        flash("Tickets cancelled successfully.")
        return redirect(url_for('cancel_tickets'))

    # Fetch PNRs for this user
    cursor.execute("SELECT DISTINCT pnr_number FROM passenger WHERE user_id = %s", (user_id,))
    pnrs = cursor.fetchall()
    passengers_by_pnr = {}

    for row in pnrs:
        pnr = row[0]
        cursor.execute("SELECT * FROM passenger WHERE pnr_number = %s AND user_id = %s", (pnr, user_id))
        passengers = cursor.fetchall()
        passengers_by_pnr[pnr] = passengers
        print(passengers_by_pnr)

    return render_template('cancel-ticket.html', passengers_by_pnr=passengers_by_pnr)

if __name__ == '__main__':
    app.run(debug=True)
