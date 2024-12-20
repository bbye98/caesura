from abc import abstractmethod
import hashlib
from pathlib import Path
import warnings


class APICFrame:
    # https://id3.org/id3v2.3.0#Attached_picture

    PICTURE_TYPES = {
        0: "Other",
        1: "32x32 pixels 'file icon' (PNG only)",
        2: "Other file icon",
        3: "Cover (front)",
        4: "Cover (back)",
        5: "Leaflet page",
        6: "Media (e.g. label side of CD)",
        7: "Lead artist/lead performer/soloist",
        8: "Artist/performer",
        9: "Conductor",
        10: "Band/Orchestra",
        11: "Composer",
        12: "Lyricist/text writer",
        13: "Recording Location",
        14: "During recording",
        15: "During performance",
        16: "Movie/video screen capture",
        17: "A bright coloured fish",
        18: "Illustration",
        19: "Band/artist logotype",
        20: "Publisher/Studio logotype",
    }

    def __init__(
        self,
        *,
        picture_type: int,
        mime_type: str,
        width: int,
        height: int,
        color_depth: int,
        data: bytes,
        description: str = "",
        n_indexed_colors: int = 0,
        size: int | None = None,
    ) -> None:
        self._type = picture_type
        self._mime_type = mime_type
        self._description = description
        self._width = width
        self._height = height
        self._color_depth = color_depth
        self._n_indexed_colors = n_indexed_colors
        self._size = size or len(data)
        self._data = data.decode() if mime_type == "-->" else data


class VorbisComment:
    # https://www.xiph.org/vorbis/doc/v-comment.html

    def __init__(self, data: bytes | dict, /,) -> None:
        if isinstance(data, bytes):
            self._vendor = data[4:(byte_offset := 4 + int.from_bytes(data[:4], byteorder="little"))].decode()
            self._n_fields = int.from_bytes(data[byte_offset:(byte_offset := byte_offset + 4)], byteorder="little")

            self._fields = {}
            for _ in range(self._n_fields):
                field_length = int.from_bytes(data[byte_offset:byte_offset + 4], byteorder="little")
                byte_offset += 4
                field = data[byte_offset:byte_offset + field_length].decode()
                byte_offset += field_length
                key, value = field.split("=", 1)
                if key in self._fields:
                    if isinstance(self._fields[key], str):
                        self._fields[key] = [self._fields[key]]
                    self._fields[key].append(value)
                else:
                    self._fields[key] = value
            # TODO: Validate for loop.
            debug=True
        elif isinstance(data, dict):
            debug=True
        else:
            raise ValueError("`data` must be either a bytes object or a dictionary.")


class Audio:
    def __init__(
        self,
        file_path: str | Path,
        /,
        *,
        tags_only: bool = False,
        validate: bool = True,
    ) -> None:
        self._file_path = Path(file_path).resolve()
        self._tags_only = tags_only
        self._validate = validate

    @abstractmethod
    def load(self) -> None:
        pass


class FLACAudio(Audio):
    # https://www.xiph.org/flac/format.html

    BLOCK_TYPES = {
        0: "STREAMINFO",
        1: "PADDING",
        2: "APPLICATION",
        3: "SEEKTABLE",
        4: "VORBIS_COMMENT",
        5: "CUESHEET",
        6: "PICTURE",
        127: "INVALID",
    }

    def __init__(
        self,
        file_path: str | Path,
        /,
        *,
        tags_only: bool = False,
        validate: bool = True,
    ) -> None:
        super().__init__(file_path, tags_only=tags_only, validate=validate)

    def load(self) -> None:
        file_path = self._file_path
        tags_only = self._tags_only
        validate = self._validate

        with open(file_path, "rb") as file:
            if file.read(4) != b"fLaC":
                raise ValueError(f"'{file_path}' is not a valid FLAC audio file.")

            self._metadata = {}
            block_header = 0x7F
            while not block_header & 0x80:
                block_header = file.read(1)[0]
                block_size = int.from_bytes(file.read(3))
                match block_type := block_header & 0x7F:
                    case 0:
                        if validate and block_size != 34:
                            raise ValueError(
                                f"Invalid STREAMINFO block size in '{file_path}'."
                            )
                        block_data = file.read(block_size)
                        if tags_only:
                            continue
                        minimum_block_size = int.from_bytes(block_data[:2])
                        maximum_block_size = int.from_bytes(block_data[2:4])
                        if validate and (
                            minimum_block_size < 16 or maximum_block_size < 16
                        ):
                            raise ValueError(
                                "Invalid minimum or maximum stream block size in "
                                f"'{file_path}'."
                            )
                        self._metadata["STREAMINFO"] = {
                            "minimum_block_size": minimum_block_size,
                            "maximum_block_size": maximum_block_size,
                            "minimum_frame_size": int.from_bytes(block_data[4:7]),
                            "maximum_frame_size": int.from_bytes(block_data[7:10]),
                            "sample_rate": int.from_bytes(block_data[10:13]) >> 4,
                            "n_channels": ((block_data[12] & 0x0E) >> 1) + 1,
                            "bits_per_sample": ((block_data[12] & 0x01) << 4)
                            + ((block_data[13] & 0xF0) >> 4)
                            + 1,
                            "total_samples": ((block_data[13] & 0x0F) << 32)
                            + int.from_bytes(block_data[14:18]),
                            "md5": hashlib.md5(block_data[18:]).hexdigest(),
                        }
                    case 1:
                        file.read(block_size)
                        if tags_only:
                            continue
                        self._metadata["PADDING"] = block_size
                    case 2:
                        if validate and (block_size - 4) % 8:
                            raise ValueError(
                                f"Invalid APPLICATION block size in '{file_path}'."
                            )
                        block_data = file.read(block_size)
                        if tags_only:
                            continue
                        self._metadata["APPLICATION"] = {
                            "id": block_data[:4].decode("utf-8"),
                            "data": block_data[4:],
                        }
                    case 3:
                        n_seek_points, remainder = divmod(block_size, 18)
                        if validate and remainder:
                            raise ValueError(
                                f"Invalid SEEKTABLE block size in '{file_path}'."
                            )
                        block_data = file.read(block_size)
                        if tags_only:
                            continue
                        self._metadata["SEEKTABLE"] = seek_table = [
                            (
                                int.from_bytes(
                                    block_data[(i := 18 * point_index) : (j := i + 8)]
                                ),
                                int.from_bytes(block_data[j : (k := j + 8)]),
                                int.from_bytes(block_data[k : k + 2]),
                            )
                            for point_index in range(n_seek_points)
                        ]
                        if validate and not all(
                            seek_table[index][0] < (sample := seek_point[0])
                            or sample == 0xFFFFFFFFFFFFFFFF
                            for index, seek_point in enumerate(seek_table[1:])
                        ):
                            raise ValueError(
                                f"Invalid SEEKTABLE block in '{file_path}'."
                            )
                    case 4:
                        self._metadata["VORBIS_COMMENT"] = VorbisComment(
                            file.read(block_size)
                        )
                        debug=True
                    case 5:
                        block_data = file.read(block_size)
                        if tags_only:
                            continue
                        if validate and (
                            block_data[136] & 0x7F
                            or block_data[137:395].rstrip(b"\x00")
                        ):
                            raise ValueError(
                                "Non-zero bits found in reserved section of "
                                f"CUESHEET block in '{file_path}'."
                            )
                        n_tracks = block_data[395]
                        byte_offset = 396
                        self._metadata["CUESHEET"] = cue_sheet = {
                            "media_catalog_number": block_data[:128]
                            .decode()
                            .rstrip("\x00")
                            or None,
                            "lead_in_samples": int.from_bytes(block_data[128:136]),
                            "cd": bool(block_data[136] >> 7),
                            "n_tracks": n_tracks,
                            "tracks": [
                                {
                                    "offset": int.from_bytes(
                                        block_data[
                                            byte_offset : (
                                                byte_offset := byte_offset + 8
                                            )
                                        ]
                                    ),
                                    "number": block_data[byte_offset],
                                    "isrc": "".join(
                                        str(b)
                                        for b in block_data[
                                            byte_offset + 1 : byte_offset + 13
                                        ]
                                        if b != 0
                                    )
                                    or None,
                                    "audio": not (
                                        block_data[byte_offset := byte_offset + 13]
                                        & 0x80
                                    ),
                                    "pre_emphasis": bool(
                                        block_data[byte_offset] & 0x40
                                    ),
                                    "n_index_points": (
                                        n_index_points := block_data[
                                            (byte_offset := byte_offset + 15) - 1
                                        ]
                                    ),
                                    "index_points": [
                                        {
                                            "offset": int.from_bytes(
                                                block_data[
                                                    (byte_offset := byte_offset + 12)
                                                    - 12 : (
                                                        index_byte := byte_offset - 4
                                                    )
                                                ]
                                            ),
                                            "number": block_data[index_byte],
                                        }
                                        for _ in range(n_index_points)
                                    ],
                                }
                                for _ in range(n_tracks)
                            ],
                        }
                        if validate:
                            cd = cue_sheet["cd"]
                            if cd:
                                if (
                                    mcn := cue_sheet["media_catalog_number"]
                                ) is not None and len(mcn) not in {
                                    0,
                                    13,
                                }:
                                    raise ValueError(
                                        "Invalid media catalog number for CD-DA cue "
                                        f"sheet in '{file_path}'."
                                    )
                                if n_tracks > 100:
                                    raise ValueError(
                                        "More than 100 tracks specified in CD-DA cue "
                                        f"sheet in '{file_path}'."
                                    )
                            elif cue_sheet["lead_in_samples"]:
                                raise ValueError(
                                    "Non-zero number of lead-in samples specified in "
                                    f"non-CD-DA cue sheet in '{file_path}'."
                                )
                            if not n_tracks:
                                raise ValueError(
                                    "No tracks specified in cue sheet in "
                                    f"'{file_path}'."
                                )

                            seen_track_numbers = set()
                            byte_offset = 396
                            for track in cue_sheet["tracks"]:
                                track_number = track["number"]
                                if cd:
                                    if track["offset"] % 588:
                                        raise ValueError(
                                            f"Invalid offset for track {track_number}"
                                            f"in CD-DA cue sheet in '{file_path}'."
                                        )
                                    if track["n_index_points"] > 100:
                                        raise ValueError(
                                            "More than 100 index points specified for "
                                            f"track {track_number} in cue sheet in "
                                            f"'{file_path}'."
                                        )
                                if track["number"]:
                                    if track["number"] in seen_track_numbers:
                                        raise ValueError(
                                            "Track with duplicate track number found "
                                            f"in cue sheet in '{file_path}'."
                                        )
                                    seen_track_numbers.add(track["number"])
                                else:
                                    raise ValueError(
                                        "Track with track number 0 found in cue "
                                        f"sheet in '{file_path}'."
                                    )
                                if (
                                    block_data[byte_offset + 21] & 0x3F
                                ) or int.from_bytes(
                                    block_data[byte_offset + 22 : byte_offset + 35]
                                ):
                                    raise ValueError(
                                        "Non-zero bits found in reserved section of "
                                        f"CUESHEET_TRACK for track {track_number} "
                                        f"in '{file_path}'."
                                    )

                                byte_offset += 36
                                if track["n_index_points"]:
                                    index_point = track["index_points"][0]
                                    index_point_number = index_point["number"]
                                    if cd and index_point["offset"] % 588:
                                        raise ValueError(
                                            "Invalid offset for index point "
                                            f"{index_point_number} of track "
                                            f"{track_number} in CD-DA cue sheet in "
                                            f"'{file_path}'."
                                        )
                                    if index_point["number"] not in {0, 1}:
                                        raise ValueError(
                                            f"First index point in track {track_number} "
                                            f"in cue sheet in '{file_path}' does not have "
                                            "index point number 0 or 1."
                                        )
                                    if int.from_bytes(
                                        block_data[byte_offset + 9 : byte_offset + 12]
                                    ):
                                        raise ValueError(
                                            "Non-zero bits found in reserved section of "
                                            "CUESHEET_TRACK_INDEX for index point "
                                            f"{index_point_number} of track "
                                            f"{track_number} in '{file_path}'."
                                        )
                                    byte_offset += 12
                                    seen_index_point_numbers = {index_point_number}
                                    previous_index_point_number = index_point_number
                                    for index_point in track["index_points"][1:]:
                                        index_point_number = index_point["number"]
                                        if cd and index_point["offset"] % 588:
                                            raise ValueError(
                                                "Invalid offset for index point "
                                                f"{index_point_number} of track "
                                                f"{track_number} in CD-DA cue sheet in "
                                                f"'{file_path}'."
                                            )
                                        if (
                                            index_point_number
                                            in seen_index_point_numbers
                                        ):
                                            raise ValueError(
                                                "Index point with duplicate index point "
                                                f"number found for track {track_number} in "
                                                f"cue sheet in '{file_path}'."
                                            )
                                        seen_index_point_numbers.add(index_point_number)
                                        if (
                                            index_point_number
                                            != previous_index_point_number + 1
                                        ):
                                            raise ValueError(
                                                "Non-sequential index point numbers found "
                                                f"in track {track_number} in cue sheet in "
                                                f"'{file_path}'."
                                            )
                                        previous_index_point_number = index_point_number
                                        if index_point_number > 99:
                                            raise ValueError(
                                                f"Index point number greater than 99 for "
                                                f"track {track_number} in cue sheet in "
                                                f"'{file_path}'."
                                            )
                                        byte_offset += 12
                            if cd:
                                if track["number"] != 170:
                                    raise ValueError(
                                        "Lead-out track does not have track number 170 in "
                                        f"CD-DA cue sheet in '{file_path}'."
                                    )
                            elif track["number"] != 255:
                                raise ValueError(
                                    "Lead-out track does not have track number 255 in "
                                    f"non-CD-DA cue sheet in '{file_path}'."
                                )
                    case 6:
                        block_data = file.read(block_size)
                        picture = APICFrame(
                            picture_type=int.from_bytes(block_data[:4]),
                            mime_type=block_data[
                                8 : (
                                    byte_offset := 8 + int.from_bytes(block_data[4:8])
                                )
                            ].decode(),
                            description=block_data[
                                byte_offset
                                + 4 : (
                                    byte_offset := byte_offset
                                    + 4
                                    + int.from_bytes(
                                        block_data[byte_offset : byte_offset + 4]
                                    )
                                )
                            ].decode(),
                            width=int.from_bytes(
                                block_data[
                                    byte_offset : (byte_offset := byte_offset + 4)
                                ]
                            ),
                            height=int.from_bytes(
                                block_data[
                                    byte_offset : (byte_offset := byte_offset + 4)
                                ]
                            ),
                            color_depth=int.from_bytes(
                                block_data[
                                    byte_offset : (byte_offset := byte_offset + 4)
                                ]
                            ),
                            n_indexed_colors=int.from_bytes(
                                block_data[
                                    byte_offset : (byte_offset := byte_offset + 4)
                                ]
                            ),
                            size=int.from_bytes(
                                block_data[
                                    byte_offset : (byte_offset := byte_offset + 4)
                                ]
                            ),
                            data=block_data[byte_offset:],
                        )
                        if pictures := self._metadata.get("PICTURE"):
                            pictures.append(picture)
                        else:
                            self._metadata["PICTURE"] = [picture]
                        # TODO: Check if front or back cover already exists.
                    case 127:
                        raise ValueError(
                            "Metadata block with invalid block type found in "
                            f"'{file_path}'."
                        )
                    case _:
                        warnings.warn(
                            f"Skipping metadata block with block type {block_type} "
                            f"(reserved) found in '{file_path}'."
                        )
                        file.read(block_size)

        debug=True

    @property
    def metadata(self):
        if not hasattr(self, "_metadata"):
            self._load()
        return self._metadata


if __name__ == "__main__":

    import os

    os.chdir("/mnt/c/Users/Benjamin/Documents/GitHub")

    # file = "06 Wrecking Ball.flac"
    file = "/mnt/c/Users/Benjamin/Documents/GitHub/caesura/tests/data/flac-test-files/subset/55 - file 48-53 combined.flac"
    flac = FLACAudio(file, tags_only=True)
    data = flac.load()

    debug = True
