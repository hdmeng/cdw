import threading
import queue
import sqlite3
import time
import datetime
import os
import socket
import json

# --- CONFIGURATION ---
DB_FOLDER = "db_data"
BATCH_SIZE = 100
QUEUE_SIZE = 10000 # Limit memory usage if writer falls behind

LISTEN_IP = '0.0.0.0' #'127.0.0.1'
LISTEN_PORT = 15010
    
# Thread-safe buffer - Item format: (timestamp, source_id, raw_data)
data_queue = queue.Queue(maxsize=QUEUE_SIZE)

# Ensure the database folder exists
os.makedirs(DB_FOLDER, exist_ok=True)

# --- HELPER: DATABASE MANAGEMENT ---
def get_db_filename(date_str):
    """Returns the full path for the daily database file."""
    return os.path.join(DB_FOLDER, f"v2x_log_{date_str}.db")

def init_db(connection):
    """Creates the table with SPECIFIC columns for your V2X data."""
    cursor = connection.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS data_stream (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            original_ip TEXT,
            psid TEXT,
            tx_channel TEXT,
            hex_payload TEXT,
            spat_message TEXT
        )
    ''') # F1 HARDCODED
    # Create an index on PSID for fast filtering later
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_psid ON data_stream(psid)')
    connection.commit()
    
def parsing(data):
    """Extracts timestamp, source_id, and payload from the wrapped packet."""
    # only used if data was wrapped with original source info
    local_timestamp = time.time()
    # 2. Convert Bytes -> String -> Dictionary
    try:
        message_str = data.decode('utf-8')      # Turn bytes into a string
        message_dict = json.loads(message_str)  # Turn string into a dict
    except json.JSONDecodeError:
        print(f"[Listener] Warning: Received malformed JSON. Skipping.")
        return None, None
    
    # 3. Extract Info - F1 HARDCODED
    original_ip = message_dict.get("original_ip", "UNKNOWN")
    payload_data = message_dict.get("payload", {})
    psid = payload_data.get("PSID", "")
    tx_channel = payload_data.get("TxChannel", "")
    hex_payload = payload_data.get("Payload", "")
    spat_message = payload_data.get("Spat1_mess", "")
    
    return (local_timestamp, original_ip, psid, tx_channel, hex_payload, spat_message)
    
    
# --- THREAD 1: THE LISTENER (Producer) ---
def listener_task():
    print("[Listener] Thread started. Listening for packets...")
    
    # TODO: Replace this block with your actual UDP socket code
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((LISTEN_IP, LISTEN_PORT))
    
    while True:
        try:
            time.sleep(0.01)  # receive data at 100Hz
            data, addr = sock.recvfrom(4096)            
            parsed_data = parsing(data)
            
            # Push to queue. If queue is full, this blocks the Listener 
            data_queue.put(parsed_data, block=True) # (Backpressure mechanism to prevent crashing RAM)
            
        except Exception as e:
            print(f"[Listener] Error: {e}")
            time.sleep(1) # Prevent tight loop on error
            
            
# --- THREAD 2: THE WRITER (Consumer) ---
def writer_task():
    print("[Writer] Thread started. Waiting for data...")
    
    current_date_str = None
    conn = None
    batch_buffer = []

    while True:
        try:
            # 1. DAILY ROTATION CHECK
            # Check date *before* processing to ensure correct file
            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
            
            if today_str != current_date_str:
                # Flush old buffer and close old connection
                if conn:
                    if batch_buffer:
                        conn.executemany("INSERT INTO data_stream (timestamp, source_id, payload) VALUES (?, ?, ?)", batch_buffer)
                        conn.commit()
                        batch_buffer = []
                        print(f"[Writer] Flushed remaining data to {current_date_str}")
                    conn.close()
                
                # Open new connection
                db_path = get_db_filename(today_str)
                print(f"[Writer] Switching to database: {db_path}")
                conn = sqlite3.connect(db_path)
                init_db(conn)
                current_date_str = today_str

            # 2. GET DATA (Blocking Wait)
            try:
                # Timeout allows loop to check date rotation even if no data flows
                record = data_queue.get(timeout=1.0) 
                batch_buffer.append(record)
            except queue.Empty:
                continue

            # 3. BATCH WRITE
            if len(batch_buffer) >= BATCH_SIZE:
                # F1 HARDCODED
                conn.executemany('''
                    INSERT INTO data_stream 
                    (timestamp, original_ip, psid, tx_channel, hex_payload, spat_message) 
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', batch_buffer)
                conn.commit()
                batch_buffer = []

        except Exception as e:
            print(f"[Writer] Critical Error: {e}")
            time.sleep(1)

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    # Create threads as "daemons" (they die when main program exits)
    t_listener = threading.Thread(target=listener_task, daemon=True)
    t_writer = threading.Thread(target=writer_task, daemon=True)

    t_listener.start()
    t_writer.start()

    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping logger...")