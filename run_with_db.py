
import app
import db

# Patch the app.py's read_data and write_data functions to use the database versions
app.read_data = db.read_data
app.write_data = db.write_data

if __name__ == "__main__":
    app.app.run(host="0.0.0.0", port=5000)
