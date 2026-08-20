export const NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', icon: 'RiDashboardLine' },
  { path: '/body-scanner', label: 'Body Scanner', icon: 'RiBodyScanLine' },
  { path: '/recommendations', label: 'Recommendations', icon: 'RiSparklingLine' },
  { path: '/stylist', label: 'AI Stylist', icon: 'RiMessage3Line' },
  { path: '/outfit-builder', label: 'Outfit Builder', icon: 'RiShirtLine' },
  { path: '/virtual-tryon', label: 'Virtual Try-On', icon: 'RiCameraLine' },
  { path: '/personalization', label: 'Personalization', icon: 'RiHeartLine' },
  { path: '/shopping', label: 'Shopping', icon: 'RiShoppingBag3Line' },
  { path: '/profile', label: 'Profile', icon: 'RiUserLine' },
  { path: '/settings', label: 'Settings', icon: 'RiSettings4Line' },
];

export const BODY_SHAPES = ['Hourglass', 'Pear', 'Rectangle', 'Apple', 'Inverted Triangle'];

export const SKIN_TONES = ['Fair', 'Light', 'Medium', 'Olive', 'Tan', 'Dark'];

export const FACE_SHAPES = ['Oval', 'Round', 'Square', 'Heart', 'Oblong', 'Diamond'];

export const OUTFIT_CATEGORIES = [
  { id: 'top', label: 'Tops', icon: '👕' },
  { id: 'bottom', label: 'Bottoms', icon: '👖' },
  { id: 'shoes', label: 'Shoes', icon: '👟' },
  { id: 'bag', label: 'Bags', icon: '👜' },
  { id: 'watch', label: 'Watches', icon: '⌚' },
  { id: 'accessories', label: 'Accessories', icon: '💍' },
];

export const SAMPLE_PRODUCTS = [
  {
    id: 1,
    name: 'Silk Blend Blazer',
    brand: 'Gucci',
    price: 2450,
    size: 'M',
    color: 'Navy',
    image: null,
    confidence: 96,
    reason: 'Perfect match for your body shape and preferred color palette',
    category: 'top',
  },
  {
    id: 2,
    name: 'Tailored Wool Trousers',
    brand: 'Prada',
    price: 890,
    size: '32',
    color: 'Charcoal',
    image: null,
    confidence: 92,
    reason: 'Complements your proportions with a flattering high-waist cut',
    category: 'bottom',
  },
  {
    id: 3,
    name: 'Leather Chelsea Boots',
    brand: 'Saint Laurent',
    price: 1195,
    size: '42',
    color: 'Black',
    image: null,
    confidence: 89,
    reason: 'Ideal heel height for your frame, matches suggested outfit palette',
    category: 'shoes',
  },
  {
    id: 4,
    name: 'Cashmere Turtleneck',
    brand: 'Loro Piana',
    price: 1650,
    size: 'M',
    color: 'Cream',
    image: null,
    confidence: 94,
    reason: 'Enhances your skin tone and provides elegant layering',
    category: 'top',
  },
  {
    id: 5,
    name: 'Classic Leather Belt',
    brand: 'Hermès',
    price: 780,
    size: '85cm',
    color: 'Brown',
    image: null,
    confidence: 88,
    reason: 'Ties together your outfit with a subtle luxury accent',
    category: 'accessories',
  },
  {
    id: 6,
    name: 'Quilted Crossbody Bag',
    brand: 'Chanel',
    price: 5200,
    size: 'Small',
    color: 'Black',
    image: null,
    confidence: 91,
    reason: 'Versatile piece that complements your style preference',
    category: 'bag',
  },
];

export const CHAT_SUGGESTIONS = [
  "What should I wear for a business meeting?",
  "Suggest a weekend brunch outfit",
  "What colors complement my skin tone?",
  "Help me build a capsule wardrobe",
  "What's trending this season?",
  "Suggest accessories for my outfit",
];
