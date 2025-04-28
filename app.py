from flask import Flask, request, render_template, redirect, url_for,flash,session, jsonify, send_file
import pymysql, io
from datetime import datetime, timedelta, date
import random, string
from fpdf import FPDF


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
                'travel_date': train1[8],
                'arrival_date': train1[9]
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
                        select distinct t.train_number, t.train_name,t.route, t.train_type, t.classes, ts1.departure_time, ts2.arrival_time, t.run_days, a.travel_date
                        from trains t
                        join train_schedule ts1 on t.train_number = ts1.train_number 
                        join train_schedule ts2 on t.train_number = ts2.train_number
                        join availability a on t.train_number = a.train_number
                        where ts1.station_name = %s and ts2.station_name = %s and a.travel_date = %s;
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
 
    cursor = conn.cursor()
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
                INSERT INTO passengers (passenger_name, age, gender, berth_preference, nationality, pnr_number, berth_allotted, seat_no,user_id,train_number,from_station, to_station, class, travel_date, booking_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
        cursor.execute(insert_query, (
                p['name'], int(p['age']), p['gender'], p['berth'], p['nationality'],
                pnr, p['berth_allotted'], p['seat_no'], session['user_id'], session['train_number'],
                session['from'],session['to'],session['class_code'], session['date'],'Confirmed'
            ))
 
        updated_passengers.append(p)

        try:
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
    session['class_code'] = request.args.get('class')
    status = request.args.get('status')

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
    return render_template('confirmation.html',train=train, date=session['date'] ,passengers=session['passengers'],class_labels=CLASS_LABELS, class_code=session['class_code'])

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
            session['user_id']= result[0]
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
            session['user_id']= result[0]
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




@app.route('/pnr_enquiry', methods=['GET', 'POST'])
def pnr_enquiry():
    ticket_details = None  
    train_numb = None
    from_station = None
    to_station = None
    class_code = None
    travel_date = None
    pnr_number = None

    if request.method == 'POST':
        pnr_number = request.form['pnr_number']

        if pnr_number:
            cursor = conn.cursor()

            # Fetch the details of passengers for the given PNR number
            cursor.execute("SELECT * FROM passengers WHERE pnr_number = %s", (pnr_number,))
            ticket_details = cursor.fetchall()

            if ticket_details:
                train_numb = ticket_details[0][11]
                from_station = ticket_details[0][12]
                to_station = ticket_details[0][13]
                class_code = ticket_details[0][14]
                travel_date = ticket_details[0][15]
                pnr_number = ticket_details[0][5]
            else:
                flash("No records found for this PNR number.", "danger")

    return render_template('pnr-enquiry.html',
                       ticket_details=ticket_details,
                       train_numb=train_numb,
                       from_station=from_station,
                       to_station=to_station,
                       class_code=class_code,
                       travel_date=travel_date,
                       pnr_number=pnr_number)




@app.route('/download_invoice/<pnr_number>')
def download_invoice(pnr_number):
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM passengers WHERE pnr_number = %s", (pnr_number,))
    ticket_details = cursor.fetchall()
    cursor.close()
    conn.close()

    if not ticket_details:
        flash("No records found for this PNR number.", "danger")
        return redirect(url_for('pnr_enquiry'))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(200, 10, txt="INDIAN RAILWAYS - IRCTC e-Ticket", ln=True, align='C')
    pdf.cell(200, 10, txt="PNR: " + ticket_details[0]['pnr_number'], ln=True)
    pdf.cell(200, 10, txt="Train No: " + ticket_details[0]['train_number'], ln=True)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(200, 10, txt="Passenger Details", ln=True)
    pdf.set_font("Arial", size=11)

    headers = ["Name", "Age", "Gender", "Seat", "Berth", "Status"]
    for header in headers:
        pdf.cell(32, 10, header, border=1)
    pdf.ln()

    for p in ticket_details:
        pdf.cell(32, 10, str(p['passenger_name']), border=1)
        pdf.cell(32, 10, str(p['passenger_age']), border=1)
        pdf.cell(32, 10, str(p['gender']), border=1)
        pdf.cell(32, 10, str(p['seat_no']), border=1)
        pdf.cell(32, 10, str(p['berth_allotted'] or p['berth_preference']), border=1)
        pdf.cell(32, 10, str(p['booking_status']), border=1)
        pdf.ln()

    pdf.ln(10)
    pdf.set_font("Arial", size=10)
    pdf.multi_cell(0, 10, "* This is a computer-generated ticket and does not require signature.\n* Please carry a valid ID proof during journey.\n* For enquiry, call 139 or visit www.irctc.co.in")

    # Convert PDF to byte stream
    pdf_bytes = pdf.output(dest='S').encode('latin1')  # Use 'latin1' for binary-safe string
    pdf_stream = io.BytesIO(pdf_bytes)

    return send_file(pdf_stream, mimetype='application/pdf',
                     download_name=f"{pnr_number}_ticket.pdf", as_attachment=True)


@app.route('/cancel_tickets', methods=['GET', 'POST'])
def cancel_tickets():
    user_id = session['user_id']  # Hardcoded for now; replace with session['user_id'] later
    cursor = conn.cursor()

    if request.method == 'POST':
        selected_ids = request.form.getlist('passenger_ids')
        for pid in selected_ids:
            cursor.execute("SELECT seat_no, train_number FROM passengers WHERE passenger_id = %s", (pid,))
            result = cursor.fetchone()
            if result:
                seat_no = result[0]
                train_number = result[1]
                # Cancel ticket
                cursor.execute("UPDATE passengers SET booking_status = 'Cancelled' WHERE passenger_id = %s", (pid,))
                # Free seat
                cursor.execute("UPDATE seat_berths SET status = 'Available' WHERE seat_number = %s AND train_number = %s", (seat_no, train_number))
        conn.commit()

        flash("Tickets cancelled successfully.")
        return redirect(url_for('cancel_tickets'))

    # Fetch PNRs for this user
    cursor.execute("SELECT DISTINCT pnr_number FROM passengers WHERE user_id = %s", (user_id,))
    pnrs = cursor.fetchall()
    passengers_by_pnr = {}

    for row in pnrs:
        pnr = row[0]
        cursor.execute("SELECT * FROM passengers WHERE pnr_number = %s AND user_id = %s", (pnr, user_id))
        passengers = cursor.fetchall()
        passengers_by_pnr[pnr] = passengers
        print(passengers_by_pnr)

    return render_template('cancel-ticket.html', passengers_by_pnr=passengers_by_pnr)




if __name__ == '__main__':
    app.run(debug=True)
