import os
import sys
import subprocess

# Get process status by name
def check_process_running(name):
    if not name:
        return False
    
    # Check if the process is running
    try:
        # Use pgrep to check if the process is running
        result = subprocess.run(
            ['pgrep', '-f', name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        # Exclude the current process (pgrep itself) from the results
        pids = [pid for pid in result.stdout.strip().split('\n') if pid and int(pid) != os.getpid()]
        output = '\n'.join(pids)
        is_running = bool(pids)
        print(f"Checking process '{name}': {output}")
        return is_running
    except Exception as e:
        print(f"Error checking process {name}: {e}")
        return False
    
if __name__ == '__main__':
   
    # get the list of process names from the command line arguments
    if len(sys.argv) < 2:
        print("Usage: python mec_process.py <process_name1> <process_name2> ...")
        sys.exit(1) 
    process_names = sys.argv[1:]
    mec_process = {}
    for name in process_names:
        is_running = check_process_running(name)
        mec_process[name] = is_running
        print(f"Process '{name}' is {'running' if is_running else 'not running'}")
