

const cv2x = {
    // Private configuration
    _config: {
        SVR_URL: 'http://128.32.129.118',
        SVR_PORT: '5000'
    },

    // Map variables
    map: null,
    lastListItem: null,
    lastMarker: null,
    mapsScriptLoaded: false,
    vmap_notloaded: true,

    lineColor: {
        64: 'green',    // egress 
        128:'blue',    // ingress
        192: 'orange' // bi-directional
    }
};

// Load Google Maps API
async function loadGoogleMapsAPI() {
    if (cv2x.mapsScriptLoaded) {
        return Promise.resolve();
    }

    // Fetch the API key from the server
    const apiKeyResponse = await fetch(`${cv2x._config.SVR_URL}:${cv2x._config.SVR_PORT}/api/key`);
    const apiKeyData = await apiKeyResponse.json();
    const apiKey = apiKeyData.api_key;

    return new Promise((resolve, reject) => {
        mapsScript = document.createElement('script');
        mapsScript.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&loading=async&callback=loadGoogleMapsAPI`; 
        mapsScript.async = true;
        mapsScript.defer = true;
        mapsScript.onload = () => {
            cv2x.mapsScriptLoaded = true;
            resolve();
        };
        mapsScript.onerror = reject;
        document.head.appendChild(mapsScript);
    });
}


/* // Create BSM trajectory map
async function bsmTraj() {
    try {
        // Wait for Google Maps to be loaded
        if (!cv2x.mapsScriptLoaded) {
            await loadGoogleMapsAPI();
        }
        
        // Create the map
        cv2x.map = new google.maps.Map(document.getElementById("bsmContent"), {
            zoom: 19,
            center: mapCenter,
            mapTypeId: 'satellite'
        });

        // Fetch initial marker coordinates from the API
        const markersResponse = await fetch(`${cv2x._config.SVR_URL}:${cv2x._config.SVR_PORT}/api/markers`);
        const markers = await markersResponse.json();
        
        // Define the custom icon
        const icon = {
            url: '../img/car-top.png',
            scaledSize: new google.maps.Size(20, 20),
        };
        
        const marker = new google.maps.Marker({
            position: markers[0],
            map: map,
            title: "Vehicle User",
            icon: icon
        });
        
        // Additional functionality...
    } catch (error) {
        console.error('Error in bsmTraj:', error);
    }
} */

async function mapValidate(site) {
    try {
        // Load the Google Maps API with the fetched API key
        await loadGoogleMapsAPI();
            
        // Fetch map center coordinates from the API
        const mapCenterResponse = await fetch(`${cv2x._config.SVR_URL}:${cv2x._config.SVR_PORT}/api/map_center?site=${site}`);
        const mapCenter = await mapCenterResponse.json();
        
        // Create the map
        cv2x.map = new google.maps.Map(document.getElementById("vmapContent"), {
            zoom: 19,
            center: mapCenter,
            mapTypeId: 'satellite'
        });
        // cv2x.map.setCenter(mapCenter);
        genIntxnList(site);

    } catch (error) {
        console.error('Error initializing map:', error);
    }
}

async function genIntxnList(site) {
    try {
        // const site = 'ECR'; // or 'ECR', depending on the desired site
        const response = await fetch(`${cv2x._config.SVR_URL}:${cv2x._config.SVR_PORT}/api/intxn_list?site=${site}`);
        const intxns = await response.json();
        if (cv2x.vmap_notloaded) {
            populateSidebar(intxns);
        }
        // set the tab notloaded flag to false
        cv2x.vmap_notloaded = false;
    } catch (error) {
        console.error('Error fetching intersection list:', error);
    }
}


async function populateSidebar(intxns) {
    const intxnList = document.getElementById('intxnList');
    intxns.forEach(intxn => {
        const listItem = document.createElement('li');
        listItem.textContent = intxn.name;
        listItem.addEventListener('click', () => {
            // set the map center to the selected intersection
            cv2x.map.setCenter(intxn.center);
            cv2x.map.setZoom(19);
                    
            // Add intersection name text at the map center using Marker
            if (cv2x.lastMarker) {
                cv2x.lastMarker.setMap(null); // Remove the previous marker
            }
            const marker = new google.maps.Marker({
                position: intxn.center,
                map: cv2x.map,
                label: {
                    text: intxn.name.substring(4),
                    color: 'white',
                    fontSize: '13px',
                    fontWeight: 'bold'
                },
                // icon: svgMarker 
            });
            cv2x.lastMarker = marker;
            // add lanes to the map
            addLanes(intxn.name);
            // change the text color back of the last selected item
            if (cv2x.lastListItem) {
                cv2x.lastListItem.style.color = 'white';
            }
            // change the text color of the selected item
            listItem.style.color = 'red';
            cv2x.lastListItem = listItem;
        });
        intxnList.appendChild(listItem);
    });
}

// add lane lines to the map with different colors for different directions
async function addLanes(selIntxnName) {
    try {
        // add lane lines
        const response = await fetch(`${cv2x._config.SVR_URL}:${cv2x._config.SVR_PORT}/api/intxn_lanes`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name: selIntxnName})
        });
        const laneLines = await response.json();
        laneLines.forEach(laneLine => {
            const line = new google.maps.Polyline({
                path: laneLine.points.map(coord => new google.maps.LatLng(coord.lat, coord.lng)),
                geodesic: true,
                strokeColor: cv2x.lineColor[laneLine.dir] || 'red',
                strokeOpacity: 0.8,
                strokeWeight: 2
            });
            line.setMap(cv2x.map);

            new google.maps.Marker({
                position: laneLine.points[0],
                map: cv2x.map,
                label: {
                    text: laneLine.id.toString(),
                    color: 'white',
                    fontSize: '11px',
                    fontWeight: 'bold'
                },
                icon: {
                    path: google.maps.SymbolPath.CIRCLE,
                    scale: 0 // Set scale to 0 to hide the icon
                }
            });
        });
    } catch (error) {
        console.error('Error obtaining lanes:', error);
    }    
}
