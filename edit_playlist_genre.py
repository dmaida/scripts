import os
import argparse
from mutagen.mp4 import MP4

def parse_m3u8(playlist_path):
    """Parse an M3U8 playlist file and return a list of audio file paths."""
    audio_files = []
    with open(playlist_path, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            # Skip comments, empty lines, or metadata lines starting with '#'
            if line and not line.startswith('#'):
                # Resolve relative paths relative to the playlist file's directory
                base_dir = os.path.dirname(playlist_path)
                file_path = os.path.normpath(os.path.join(base_dir, line)) if base_dir else line
                # Check if file exists and has .m4a extension
                if os.path.isfile(file_path) and file_path.lower().endswith('.m4a'):
                    audio_files.append(file_path)
    return audio_files

def update_tags(audio_path, genre=None, comment=None, replace=False):
    """Update the genre and/or comment tags of an M4A audio file."""
    try:
        audio = MP4(audio_path)
        # Get current genre and comment (using the correct tag keys '©gen' and '©cmt')
        current_genre = audio.get('©gen', [''])[0]
        current_comment = audio.get('©cmt', [''])[0]
        print(f"Current genre for {audio_path}: {current_genre}")
        print(f"Current comment for {audio_path}: {current_comment}")
        
        # Update genre if provided
        if genre:
            new_genre = genre if replace else f"{current_genre}, {genre}".strip(', ')
            if not new_genre:
                new_genre = genre  # Ensure genre is set if current_genre is empty
            audio['©gen'] = new_genre
            print(f"Updated genre for {audio_path}: {new_genre}")
        
        # Update comment if provided
        if comment:
            new_comment = comment if replace else f"{current_comment}, {comment}".strip(', ')
            if not new_comment:
                new_comment = comment  # Ensure comment is set if current_comment is empty
            audio['©cmt'] = new_comment
            print(f"Updated comment for {audio_path}: {new_comment}")
        
        # Save changes if at least one tag was updated
        if genre or comment:
            audio.save()
        else:
            print(f"No changes made to {audio_path}: No genre or comment provided")
            
    except Exception as e:
        print(f"Error updating {audio_path}: {e}")

def main():
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Append or replace genre and/or comment for all M4A songs in an M3U8 playlist.")
    parser.add_argument('--playlist', required=True, help="Path to the M3U8 playlist file")
    parser.add_argument('--genre', help="Genre to append or replace")
    parser.add_argument('--comment', help="Comment to append or replace")
    parser.add_argument('--replace', action='store_true', help="Replace the existing genre and/or comment instead of appending")
    args = parser.parse_args()

    # Validate that at least one of genre or comment is provided
    if not args.genre and not args.comment:
        print("Error: At least one of --genre or --comment must be provided.")
        return

    # Validate playlist file
    if not os.path.isfile(args.playlist):
        print(f"Error: Playlist file '{args.playlist}' does not exist.")
        return

    # Parse the playlist
    audio_files = parse_m3u8(args.playlist)
    if not audio_files:
        print("No valid M4A audio files found in the playlist.")
        return

    # Update tags for each audio file
    for audio_file in audio_files:
        update_tags(audio_file, args.genre, args.comment, args.replace)

if __name__ == "__main__":
    main()