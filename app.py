import math
from flask import send_file
import io
import json
# Helper: Haversine distance in km
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# Cluster pins by theme and max 1km distance
def cluster_pins(pins, max_dist_km=1.0):
    clusters_by_theme = {}
    for theme in set(pin['theme'] for pin in pins):
        theme_pins = [p for p in pins if p['theme'] == theme]
        clusters = []
        for pin in theme_pins:
            added = False
            for cluster in clusters:
                # If pin is within 1km of any pin in cluster, add to cluster
                if any(haversine(pin['lat'], pin['lng'], cpin['lat'], cpin['lng']) <= max_dist_km for cpin in cluster['pins']):
                    cluster['pins'].append(pin)
                    added = True
                    break
            if not added:
                clusters.append({'pins': [pin]})
        # Compute cluster center
        for cluster in clusters:
            lats = [p['lat'] for p in cluster['pins']]
            lngs = [p['lng'] for p in cluster['pins']]
            cluster['center'] = {
                'lat': sum(lats)/len(lats),
                'lng': sum(lngs)/len(lngs)
            }
        clusters_by_theme[theme] = clusters
    return clusters_by_theme

# Export clusters for a specific theme as GeoJSON
@app.route('/api/clusters/<theme>.geojson')
def export_theme_clusters_geojson(theme):
    clusters_by_theme = cluster_pins(pins)
    clusters = clusters_by_theme.get(theme, [])
    geojson = {
        'type': 'FeatureCollection',
        'features': []
    }
    for cluster in clusters:
        feature = {
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [cluster['center']['lng'], cluster['center']['lat']]
            },
            'properties': {
                'theme': theme,
                'pins': cluster['pins']
            }
        }
        geojson['features'].append(feature)
    buf = io.BytesIO()
    buf.write(json.dumps(geojson, indent=2).encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='application/geo+json', as_attachment=True, download_name=f'{theme}_clusters.geojson')

# Endpoint to list available themes
@app.route('/api/themes')
def list_themes():
    themes = list(set(pin['theme'] for pin in pins))
    return jsonify(themes)

from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# In-memory storage for pins
pins = []

@app.route('/')
def home():
    return render_template('index.html')

# API to get all pins
@app.route('/api/pins', methods=['GET'])
def get_pins():
    return jsonify(pins)


# API to add a new pin
@app.route('/api/pins', methods=['POST'])
def add_pin():
    data = request.get_json()
    # Expecting: {"lat": float, "lng": float, "theme": str, "name": str, "description": str}
    if not all(k in data for k in ("lat", "lng", "theme", "name", "description")):
        return jsonify({"error": "Missing data"}), 400
    pin = {
        "lat": data["lat"],
        "lng": data["lng"],
        "theme": data["theme"],
        "name": data["name"],
        "description": data["description"]
    }
    pins.append(pin)
    return jsonify(pin), 201

if __name__ == '__main__':
    app.run(debug=True)
