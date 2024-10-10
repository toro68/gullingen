import React from 'react';

const MapMarker = ({ color, size = 24 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <circle cx="12" cy="12" r="10" fill={color} fillOpacity="0.8" />
    <circle cx="12" cy="12" r="6" fill={color} />
  </svg>
);

export default MapMarker;

// Bruk av komponenten:
// <MapMarker color="#0000FF" size={30} />