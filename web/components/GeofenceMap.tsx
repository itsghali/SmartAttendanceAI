"use client";

import { useEffect, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Circle, Polygon, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";

import { BoundaryType, Geofence } from "../lib/geofenceService";

// Leaflet's default marker icon resolves image URLs relative to its CSS,
// which breaks under Next.js's bundler. A small CSS divIcon sidesteps that
// entirely instead of wiring up asset rewrites for three PNGs.
function dot(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 2px rgba(0,0,0,0.5)"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

const DRAFT_ICON = dot("#2563eb");

const DEFAULT_CENTER: [number, number] = [36.8065, 10.1815];

interface GeofenceMapProps {
  mode: BoundaryType;
  center: [number, number] | null;
  radiusMeters: number;
  polygonPoints: [number, number][];
  onCenterChange: (center: [number, number]) => void;
  onPolygonPointAdd: (point: [number, number]) => void;
  existingGeofences?: Geofence[];
  // MapContainer's own center/zoom props only apply on first mount (react-leaflet
  // treats the map as uncontrolled after that). Bump focusToken to force an
  // imperative pan/zoom — e.g. when the "Edit" button loads a distant site.
  focusPoint?: [number, number] | null;
  focusToken?: number;
}

function FlyTo({ point, token }: { point: [number, number] | null | undefined; token: number | undefined }) {
  const map = useMap();
  useEffect(() => {
    if (point) {
      map.flyTo(point, 14);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);
  return null;
}

function ClickHandler({
  mode,
  onCenterChange,
  onPolygonPointAdd,
}: {
  mode: BoundaryType;
  onCenterChange: (center: [number, number]) => void;
  onPolygonPointAdd: (point: [number, number]) => void;
}) {
  useMapEvents({
    click(e) {
      const point: [number, number] = [e.latlng.lat, e.latlng.lng];
      if (mode === "circle") {
        onCenterChange(point);
      } else {
        onPolygonPointAdd(point);
      }
    },
  });
  return null;
}

export default function GeofenceMap({
  mode,
  center,
  radiusMeters,
  polygonPoints,
  onCenterChange,
  onPolygonPointAdd,
  existingGeofences = [],
  focusPoint,
  focusToken,
}: GeofenceMapProps) {
  const mapCenter = center ?? DEFAULT_CENTER;

  const existingOverlays = useMemo(
    () =>
      existingGeofences.filter((g) => g.is_active),
    [existingGeofences],
  );

  return (
    <MapContainer
      center={mapCenter}
      zoom={14}
      style={{ height: "100%", width: "100%" }}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ClickHandler mode={mode} onCenterChange={onCenterChange} onPolygonPointAdd={onPolygonPointAdd} />
      <FlyTo point={focusPoint} token={focusToken} />

      {existingOverlays.map((g) =>
        g.boundary_type === "circle" && g.center_latitude != null && g.center_longitude != null ? (
          <Circle
            key={g.id}
            center={[g.center_latitude, g.center_longitude]}
            radius={g.radius_meters ?? 0}
            pathOptions={{ color: "#9ca3af", fillOpacity: 0.05, dashArray: "4" }}
          />
        ) : g.boundary_type === "polygon" && g.polygon_points ? (
          <Polygon
            key={g.id}
            positions={g.polygon_points.map((p) => [p.latitude, p.longitude])}
            pathOptions={{ color: "#9ca3af", fillOpacity: 0.05, dashArray: "4" }}
          />
        ) : null,
      )}

      {mode === "circle" && center && (
        <>
          <Marker position={center} icon={DRAFT_ICON} />
          <Circle center={center} radius={radiusMeters} pathOptions={{ color: "#2563eb" }} />
        </>
      )}

      {mode === "polygon" && polygonPoints.length > 0 && (
        <>
          {polygonPoints.map((p, i) => (
            <Marker key={i} position={p} icon={DRAFT_ICON} />
          ))}
          {polygonPoints.length >= 2 && (
            <Polygon positions={polygonPoints} pathOptions={{ color: "#2563eb" }} />
          )}
        </>
      )}
    </MapContainer>
  );
}
