from flask import Flask, request, render_template, redirect, url_for,flash,session, jsonify
import pymysql
from datetime import datetime, timedelta, date

conn = pymysql.connect(
    host="127.0.0.1",       
    user="root",
    password="root",
    database="train-booking",
    #port=3306,  
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

    print(f"Received train_number: {train_number}, class_code: {class_code}")  # Debugging line

    results = []

    try:
        with conn.cursor() as cursor:
            query = """
                SELECT travel_date AS date, timing, wl_status AS wl
                FROM availability
                WHERE train_number = %s AND class_code = %s
                ORDER BY travel_date
                LIMIT 5
            """
            cursor.execute(query, (train_number, class_code))
            rows = cursor.fetchall()

            if rows:
                for row1 in rows:
                    row = list(row1)
                    if isinstance(row[1], timedelta):
                        row[1] = str(row[1])

                    results.append({
                        "date": row[0].strftime('%a, %d %b'),  # Ensure date is string formatted
                        "timing": row[1],  # Now it's a string, so it's JSON serializable
                        "wl": row[2]
                    })
            else:
                print("No data found for this query.")  # Debugging line

    except Exception as e:
        print(f"Error during database query: {e}")  # Debugging line

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

@app.route('/')
def index():
    cursor = conn.cursor()
    cursor.execute("""select station_name from station
                        order by station_name;""")    
    stations = [row[0] for row in cursor.fetchall()]
    today = date.today().isoformat()
    return render_template('index.html', stations=stations, today=today, class_labels=CLASS_LABELS)

@app.route('/search')
def search():
    from_station = request.args.get('from', '').strip()
    to_station = request.args.get('to', '').strip()
    class_type = request.args.get('class_type', '').strip()

    matching_trains = []

    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM trains")
        trains = cursor.fetchall()
        for train1 in trains:
            train= {
                'id': train1[0],
                'number': train1[1],
                'name': train1[2],
                'route': train1[3],
                'type': train1[4],
                'classes': train1[5],
                'departure_time': train1[6],
                'arrival_time': train1[7],
                'days': train1[8],
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
                    train['journey_date'] = datetime.now().strftime('%Y-%m-%d')
                    matching_trains.append(train)

    return render_template('train-list.html',
                           trains=matching_trains,
                           from_station=from_station,
                           to_station=to_station,
                           class_type=class_type,
                           class_labels=CLASS_LABELS)



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
                'id': row[0],
                'number': row[1],
                'name': row[2],
                'route': row[3],
                'type': row[4],
                'classes': row[5],
                'departure_time': row[6],
                'arrival_time': row[7],
                'run_days': row[8],
                'duration': calculate_duration(row[6], row[7]),
            }

    except Exception as e:
        return f"Database error: {e}", 500

    return render_template('booking.html',
                           train=train,
                           class_code=class_code,
                           date=date,
                           wl=status,
                           class_labels=CLASS_LABELS)

@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    train = request.form['train']
    cls = request.form['class']
    date = request.form['date']
    status = request.form['status']
    return f"Booking confirmed for Train {train} on {date} in {cls} ({status})"

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
            return redirect(url_for('home'))
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
