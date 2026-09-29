const BODY_SHAPE_MAP = {
  hourglass: 'Hourglass',
  pear: 'Pear',
  rectangle: 'Rectangle',
  apple: 'Apple',
  inverted_triangle: 'Inverted Triangle',
  unknown: 'Unknown',
};

const FACE_SHAPE_MAP = {
  oval: 'Oval',
  round: 'Round',
  square: 'Square',
  heart: 'Heart',
  long: 'Oblong',
  diamond: 'Diamond',
  unknown: 'Unknown',
};

const SKIN_DEPTH_MAP = {
  fair: 'Fair',
  light: 'Light',
  medium: 'Medium',
  tan: 'Tan',
  deep: 'Dark',
  unknown: 'Unknown',
};

const UNDERTONE_MAP = {
  warm: 'Warm',
  cool: 'Cool',
  neutral: 'Neutral',
  unknown: 'Unknown',
};

const GENDER_MAP = {
  male: 'Male',
  female: 'Female',
  unknown: 'Unknown',
};

export function mapBodyShape(raw) {
  return BODY_SHAPE_MAP[raw] || raw;
}

export function mapFaceShape(raw) {
  return FACE_SHAPE_MAP[raw] || raw;
}

export function mapSkinDepth(raw) {
  return SKIN_DEPTH_MAP[raw] || raw;
}

export function mapUndertone(raw) {
  return UNDERTONE_MAP[raw] || raw;
}

export function mapGender(raw) {
  return GENDER_MAP[raw] || raw;
}
