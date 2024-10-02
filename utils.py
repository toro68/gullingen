import toml
import re

def map_cabins_to_users(toml_file_path):
    # Load the TOML file
    config = toml_file_path

    # Extract cabin coordinates and user data
    cabin_coordinates = config.get('cabin_coordinates', {})
    users = config.get('auth_codes', {}).get('users', {})

    # Create a mapping of cabin numbers to user names
    cabin_user_map = {}
    for username, _ in users.items():
        match = re.match(r'^(\d+),', username)
        if match:
            cabin_number = match.group(1)
            cabin_user_map[cabin_number] = username

    # Create the final mapping of cabin data to users
    result = {}
    for cabin_id, coordinates in cabin_coordinates.items():
        user = cabin_user_map.get(cabin_id)
        if user:
            result[user] = {
                'cabin_number': cabin_id,
                'latitude': coordinates['latitude'],
                'longitude': coordinates['longitude'],
                'rode': coordinates['rode'],
                'icon': coordinates['icon']
            }

    return result

# Example usage:
# toml_file_path = 'path/to/your/config.toml'
# cabin_user_data = map_cabins_to_users(toml_file_path)
# for user, data in cabin_user_data.items():
#     print(f"User: {user}")
#     print(f"Cabin: {data['cabin_number']}")
#     print(f"Coordinates: {data['latitude']}, {data['longitude']}")
#     print(f"Rode: {data['rode']}")
#     print(f"Icon: {data['icon']}")
#     print("---")
