from flask import Flask, request, render_template, redirect, url_for,flash,session, jsonify
import pymysql
from datetime import datetime, timedelta, date
import random, string


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
    cursor = conn.cursor()
    cursor.execute("""select station_name from station
                        order by station_name;""")    
    stations = [row[0] for row in cursor.fetchall()]
    today = date.today().isoformat()
    return render_template('index.html', stations=stations, today=today, class_labels=CLASS_LABELS)

@app.route('/ticket-list')
def search():
    from_station = request.args.get('from', '').strip()
    to_station = request.args.get('to', '').strip()
    class_type = request.args.get('class_type', '').strip()
    travel_date = request.args.get('date','').strip()


    matching_trains = []

    with conn.cursor() as cursor:
        query = """
                        select distinct t.train_number, t.train_name,t.route, t.train_type, t.classes, ts1.departure_time, ts2.arrival_time, t.run_days, a.travel_date
                        from trains t
                        join train_schedule ts1 on t.train_number = ts1.train_number 
                        join train_schedule ts2 on t.train_number = ts2 .train_number
                        join availability a on t.train_number = a.train_number
                        where ts1.station_name = %s and ts2.station_name = %s and a.travel_date = %s;
                       """
        val = (from_station, to_station,travel_date,)
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
    train_no = 12633  #session.get('train_no')
    class_code = '2S' #session.get('class_code')
 
    updated_passengers = []
 
    # Determine if class uses seating or sleeper-type preference
    if class_code in ['2S', 'GN']:
        berth_types = ['Window', 'Middle', 'Aisle']
        pref_type = 'seating'
    else:
        berth_types = ['Lower', 'Middle', 'Upper', 'Side Lower', 'Side Upper']
        pref_type = 'sleeper'
 
    seat_counts = {bt: 0 for bt in berth_types}
    seat_counts['rac'] = 6
 
    with conn.cursor() as cursor:
        query = """
            SELECT berth_type, COUNT(*) FROM seat_berths
            WHERE train_number = %s AND class_code = %s AND status = 'Available'
            GROUP BY berth_type
        """
        cursor.execute(query, (train_no, class_code))
        for row in cursor.fetchall():
            berth_type, count = row
            if berth_type in seat_counts:
                seat_counts[berth_type] = count
 
    seat_count_list = [seat_counts[bt] for bt in berth_types] + [seat_counts['rac']]
 
    with conn.cursor() as cursor:
        for p in passengers:
            pref_code = p['berth']
            allotted_berth = preference(pref_code, seat_count_list, pref_type)
 
            if allotted_berth != 'waiting' and allotted_berth != 'rac':
                seat_query = """
                    SELECT seat_number FROM seat_berths
                    WHERE train_number = %s AND class_code = %s AND berth_type = %s AND status = 'Available'
                    LIMIT 1
                """
                cursor.execute(seat_query, (train_no, class_code, allotted_berth))
                seat_row = cursor.fetchone()
 
                if seat_row:
                    seat_no = seat_row[0]
                    update_query = """
                        UPDATE seat_berths
                        SET status = 'Booked'
                        WHERE train_number = %s AND class_code = %s AND seat_number = %s
                    """
                    cursor.execute(update_query, (train_no, class_code, seat_no))
                else:
                    seat_no = "Waiting"
            else:
                seat_no = "Waiting"
 
            p['berth_allotted'] = allotted_berth
            p['seat_no'] = seat_no
 
            insert_query = """
                INSERT INTO passengers (name, age, gender, berth_preference, nationality, pnr, berth_allotted, seat_no)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(insert_query, (
                p['name'], int(p['age']), p['gender'], p['berth'], p['nationality'],
                pnr, p['berth_allotted'], p['seat_no']
            ))
 
            updated_passengers.append(p)

            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT * FROM trains WHERE train_number = %s", (session['train_number'],))
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
                    }

            except Exception as e:
                return f"Database error: {e}", 500
 
 
        conn.commit()
 
    return render_template('summary.html', train=train,pnr=pnr,class_labels=CLASS_LABELS, passengers=updated_passengers)

@app.route('/book')
def book():
    train_number = request.args.get('train')
    class_code = request.args.get('class')
    date = request.args.get('date')
    status = request.args.get('status')

    if not train_number:
        return "Train number missing", 400

    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM trains WHERE train_number = %s", (train_number,))
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
            }

            session['train_number'] = train['number']


    except Exception as e:
        return f"Database error: {e}", 500

    return render_template('passenger-details.html',
                           train=train,
                           class_code=class_code,
                           date=date,
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
            cursor.execute("SELECT * FROM trains WHERE train_number = %s", (session['train_number'],))
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
        }

    except Exception as e:
        return f"Database error: {e}", 500
 
    session['passengers'] = list(passengers.values())
    session['class_code'] = form.get('class_code')
    return render_template('confirmation.html',train=train ,passengers=session['passengers'],class_labels=CLASS_LABELS)

@app.route('/login', methods=['GET','POST'])
def login_user():
    if request.method == 'POST':
        cursor = conn.cursor()
        user_name = request.form['user-name']
        user_password = request.form['user-password']
        sql = "SELECT * FROM users WHERE user_name = %s AND password = %s"
        val = (user_name, user_password)
        cursor.execute(sql, val)
        result = cursor.fetchone()
        if result:
            session['user_logged_in'] = True
            session['user_name'] = result[1] 
            return redirect(url_for('index'))
        else:
            return "Invalid credentials"
    elif request.method == 'GET':
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

        sql = "INSERT INTO users (user_name, full_name, email, number, password) VALUES (%s, %s, %s, %s, %s)"
        val = (user_name, full_name, user_email,user_number,user_password)
        cursor.execute(sql, val)
        conn.commit()
        return redirect(url_for('login_user'))
    
    elif request.method == 'GET':
        return render_template('signup.html')


if __name__ == '__main__':
    app.run(debug=True)
