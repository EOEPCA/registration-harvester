import folium
from folium.plugins import TimestampedGeoJson
from eodag import SearchResult

def map_results(bbox, results):
    # The GeoJSON representation has to be slightly adapted for the time slider
    adapted_prods = SearchResult.as_dict(results)
    for feature in adapted_prods["features"]:
        feature["properties"]["time"] = feature["properties"]["start_datetime"]
    
    # Create a map zoomed over the search area
    fmap = folium.Map([48, 11.5], zoom_start=8)

    if bbox:
        print(False)
        bbox_coords = [[47.9, 11.0], [48.3, 11.7]]
        folium.Rectangle(
            bounds=bbox_coords,
            color="#ff7800",       # Rahmenfarbe
            fill=True,             # Fläche füllen
            fill_color="#ffff00",  # Füllfarbe
            fill_opacity=0.2,      # Transparenz
            popup="Suchbereich Ammersee-München"
        ).add_to(fmap)
    
    # Add layer that temporally maps the products found
    TimestampedGeoJson(
        adapted_prods,
        transition_time=50,  # Transition duration in ms
        period="PT3H",  # Array of times, here every 3 hours
        duration="PT12H",  # Feature display duragion, here 6 hours
        time_slider_drag_update=True,  # Update the map when the slider is dragged
        auto_play=False,  # Don't auto play the animation
    ).add_to(fmap)
    return fmap