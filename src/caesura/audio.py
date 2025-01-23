from abc import abstractmethod
from datetime import datetime
import hashlib
from numbers import Number
from pathlib import Path
import re
from typing import Any, Sequence
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
    """
    Vorbis comment object.

    .. seealso::

        For more information, see `Ogg Vorbis I format specification:
        comment field and header specification
        <https://www.xiph.org/vorbis/doc/v-comment.html>`_.
    """

    def __init__(
        self, bytestream: bytes | None = None, /, *, ignore_duplicates: bool = False
    ) -> None:
        """
        Parameters
        ----------
        bytestream : bytes, positional-only, optional
            Bytestream containing a Vorbis comment metadata block.

        ignore_duplicates : bool, keyword-only, default: :code:`False`
            Specifies whether to ignore duplicate values in existing fields.
        """

        if isinstance(bytestream, bytes):
            self._vendor = bytestream[
                4 : (
                    byte_offset := 4
                    + int.from_bytes(bytestream[:4], byteorder="little")
                )
            ].decode()
            self._n_fields = int.from_bytes(
                bytestream[byte_offset : (byte_offset := byte_offset + 4)],
                byteorder="little",
            )
            self._fields = {}
            if ignore_duplicates:
                for _ in range(self._n_fields):
                    field_length = int.from_bytes(
                        bytestream[byte_offset : (byte_offset := byte_offset + 4)],
                        byteorder="little",
                    )
                    field = bytestream[
                        byte_offset : (byte_offset := byte_offset + field_length)
                    ].decode()
                    key, value = field.split("=", 1)
                    if (key := key.upper()) in self._fields:
                        self._fields[key][value] = None
                    else:
                        self._fields[key] = {value: None}
                for key, value in self._fields.items():
                    self._fields[key] = list(value.keys())
            else:
                for _ in range(self._n_fields):
                    field_length = int.from_bytes(
                        bytestream[byte_offset : (byte_offset := byte_offset + 4)],
                        byteorder="little",
                    )
                    field = bytestream[
                        byte_offset : (byte_offset := byte_offset + field_length)
                    ].decode()
                    key, value = field.split("=", 1)
                    if (key := key.upper()) in self._fields:
                        self._fields[key].append(value)
                    else:
                        self._fields[key] = [value]
        elif bytestream is None:
            self._vendor = None
            self._n_fields = 0
            self._fields = {}
        else:
            raise ValueError("If provided, `bytestream` must be a bytes object.")

        self._ignore_duplicates = ignore_duplicates

    def get(self):
        pass

    def set(self, **kwargs: Any) -> None:
        """
        Set track attributes.

        .. note::

           The Vorbis comment specification allows for arbitrary
           case-insensitive field names consisting of only ASCII
           characters 0x20 through 0x7D, excluding 0x3D (:code:`=`).
           However, Python identifiers are case-sensitive, can contain
           Unicode characters, and have restrictions like not containing
           whitespace or starting with a digit.

           To pass in fields with names that do not conform to Python
           identifier rules, unpack a dictionary containing key–value
           pairs.

           All field names will have illegal characters replaced with
           underscores and be converted to uppercase. It is possible
           that two fields with different invalid names are treated as
           the same field if their sanitized names are identical.

        Parameters
        ----------
        **kwargs
            Key–value pairs of track attributes.

        Examples
        --------
        >>> vc = VorbisComment()
        >>> vc.set(title="I Found U", artist=["Passion Pit", "Galantis"])
        >>> vc.set(
        ...     ALBUM="Church",
        ...     ALBUMARTIST="Galantis"
        ... )
        >>> vc.set(
        ...     compilation=False,
        ...     date=datetime(2019, 5, 15, 12, 0, 0),
        ...     tracknumber=9,
        ...     tracktotal=14
        ... )
        >>> vc.set(**{"日本語版": True})
        """

        to_string = lambda value: (
            value if isinstance(value, str)
            else value.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(value, datetime)
            else str(int(value)) if isinstance(value, bool)
            else str(value) if isinstance(value, Number)
            else value
        )

        if self._ignore_duplicates:
            new_keys = set()
            for key, value in kwargs.items():
                if not isinstance(key, str):
                    raise TypeError(f"Field name `{key}` is not a `str`.")
                if (
                    key := re.sub("[^\x20-\x3C\x3E-\x7E]", "_", key.upper())
                ) not in self._fields:
                    self._fields[key] = {}
                    new_keys.add(key)
                if isinstance(value := to_string(value), str):
                    self._fields[key][value] = None
                elif isinstance(value, Sequence):
                    for item in value:
                        if isinstance(item := to_string(item), str):
                            self._fields[key][item] = None
                        else:
                            raise TypeError(
                                f"The value `{item}` for field '{key}' has "
                                f"unsupported type `{type(item).__name__}`."
                            )
                else:
                    raise TypeError(
                        f"The value `{value}` for field '{key}' has "
                        f"unsupported type `{type(value).__name__}`."
                    )
            for key in new_keys:
                self._fields[key] = list(self._fields[key].keys())
        else:
            for key, value in kwargs.items():
                if not isinstance(key, str):
                    raise TypeError("Field names must be strings.")
                if (
                    key := re.sub("[^\x20-\x3C\x3E-\x7E]", "_", key.upper())
                ) not in self._fields:
                    self._fields[key] = []
                if isinstance(value := to_string(value), str):
                    self._fields[key].append(value)
                elif isinstance(value, Sequence):
                    for item in value:
                        if isinstance(item := to_string(item), str):
                            self._fields[key].append(item)
                        else:
                            raise TypeError(
                                f"The value `{item}` for field '{key}' has "
                                f"unsupported type `{type(item).__name__}`."
                            )
                else:
                    raise TypeError(
                        f"The value `{value}` for field '{key}' has "
                        f"unsupported type `{type(value).__name__}`."
                    )

    @property
    def album(self) -> list[str] | None:
        """
        Name of the album or collection containing the track.
        """

        return self._fields.get("ALBUM")

    @property
    def album_artist(self) -> list[str] | None:
        """
        Main artist(s) of the entire album.
        """

        return self._fields.get("ALBUMARTIST")

    @property
    def artist(self) -> list[str] | None:
        """
        Artist(s) responsible for the track (e.g., the performing band
        or singer in popular music, the composer for classical music, or
        the author of the original text in audiobooks).
        """

        return self._fields.get("ARTIST")

    @property
    def comment(self) -> list[str] | None:
        """
        Free-form comment(s) about the track.
        """

        return self._fields.get("COMMENT")

    @property
    def composer(self) -> list[str] | None:
        """
        Composer(s) who wrote the track.
        """

        return self._fields.get("COMPOSER")

    @property
    def contact(self) -> list[str] | None:
        """
        Contact information for the creators or distributors of the
        track.
        """

        return self._fields.get("CONTACT")

    @property
    def copyright(self) -> list[str] | None:
        """
        Copyright attribution for the track or album.
        """

        return self._fields.get("COPYRIGHT")

    @property
    def date(self) -> list[str] | None:
        """
        Track release date.
        """

        return self._fields.get("DATE", self._fields.get("YEAR"))

    @property
    def description(self) -> list[str] | None:
        """
        General description of the track or album.
        """

        return self._fields.get("DESCRIPTION")

    @property
    def disc_number(self) -> list[str] | None:
        """
        Disc number within a multi-disc album.
        """

        return self._fields.get("DISCNUMBER")

    @property
    def disc_total(self) -> list[str] | None:
        """
        Total number of discs in the album set.
        """

        return self._fields.get("DISCTOTAL")

    @property
    def encoder(self) -> list[str] | None:
        """
        Software or hardware used to encode the track.
        """

        return self._fields.get("ENCODER")

    @property
    def genre(self) -> list[str] | None:
        """
        Genre(s) of the track.
        """

        return self._fields.get("GENRE")

    @property
    def isrc(self) -> list[str] | None:
        """
        International Standard Recording Code (ISRC) for the particular
        recording in the track.
        """

        return self._fields.get("ISRC")

    @property
    def license(self) -> list[str] | None:
        """
        License information for the track or album.
        """

        return self._fields.get("LICENSE")

    @property
    def location(self) -> list[str] | None:
        """
        Location where the recording was made.
        """

        return self._fields.get("LOCATION")

    @property
    def organization(self) -> list[str] | None:
        """
        Publisher or record label distributing the track.
        """

        return self._fields.get("ORGANIZATION")

    @property
    def performer(self) -> list[str] | None:
        """
        Performer(s) responsible for the track (e.g., the conductor,
        orchestra, and/or soloists in classical music, or the narrator
        in audiobooks).
        """

        return self._fields.get("PERFORMER")

    @property
    def title(self) -> list[str] | None:
        """
        Title of the track.
        """

        return self._fields.get("TITLE")

    @property
    def track_number(self) -> list[str] | None:
        """
        Track number within the album.
        """

        return self._fields.get("TRACKNUMBER")

    @property
    def track_total(self) -> list[str] | None:
        """
        Total number of tracks in the album.
        """

        return self._fields.get("TRACKTOTAL")

    @property
    def version(self) -> list[str] | None:
        """
        Version of the track (e.g., remix information).
        """

        return self._fields.get("VERSION")


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
                                8 : (byte_offset := 8 + int.from_bytes(block_data[4:8]))
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

        debug = True

    @property
    def metadata(self):
        if not hasattr(self, "_metadata"):
            self.load()
        return self._metadata