import logging
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Dict
from tracelog import trace


@dataclass
class SensorZone:
    zone_id: str
    calibration_factor: float
    zone_offset: float
    sampling_rate: int
    threshold_max: float


@dataclass
class RawReading:
    zone_id: str
    value: float
    sample_count: int


@dataclass
class NormalizedReading:
    zone_id: str
    calibrated_value: float
    confidence: float


class Scenario:
    def __init__(self, logger):
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.buffer: List[NormalizedReading] = []
        self._zones = {
            "Zone-1": SensorZone("Zone-1", 1.05, 0.02, 10, 5.0),
            "Zone-2": SensorZone("Zone-2", 1.08, 5.50, 10, 5.0),
            "Zone-3": SensorZone("Zone-3", 1.03, 0.01, 10, 5.0),
        }
        self._raw_values = {
            "Zone-1": [42.1, 43.5, 41.8, 44.2, 42.9],
            "Zone-2": [38.7, 39.2, 38.5, 40.1, 39.8],
            "Zone-3": [51.3, 52.0, 50.8, 51.7, 52.4],
        }

    @trace
    def read_raw_signal(self, zone: SensorZone) -> RawReading:
        self.logger.info(f"Reading raw signal from {zone.zone_id}")
        values = self._raw_values[zone.zone_id]
        avg = sum(values) / len(values)
        reading = RawReading(zone_id=zone.zone_id, value=avg, sample_count=len(values))
        self.logger.debug(f"{zone.zone_id} raw average: {avg:.4f} from {len(values)} samples")
        return reading

    @trace
    def normalize_reading(self, reading: RawReading, zone: SensorZone) -> float:
        self.logger.info(f"Normalizing reading for {zone.zone_id}")
        normalized = reading.value / zone.sampling_rate
        self.logger.debug(f"{zone.zone_id} normalized: {normalized:.4f}")
        return normalized

    @trace
    def apply_calibration(self, normalized: float, zone: SensorZone) -> float:
        self.logger.info(f"Applying calibration for {zone.zone_id}")
        calibrated = normalized * zone.zone_offset
        self.logger.debug(f"{zone.zone_id}: {normalized:.4f} x {zone.zone_offset} = {calibrated:.4f}")
        return calibrated

    @trace
    def compute_confidence(self, reading: RawReading, zone: SensorZone) -> float:
        self.logger.debug(f"Computing confidence for {zone.zone_id}: samples={reading.sample_count}")
        return min(1.0, reading.sample_count / 10.0)

    @trace
    def push_to_buffer(self, zone_id: str, calibrated: float, confidence: float):
        self.logger.info(f"Pushing reading from {zone_id} to buffer: value={calibrated:.4f}")
        reading = NormalizedReading(zone_id=zone_id, calibrated_value=calibrated, confidence=confidence)
        self.buffer.append(reading)
        self.logger.debug(f"Buffer size: {len(self.buffer)}")

    @trace
    def collect_zone_data(self, zone_id: str):
        self.logger.info(f"Collector started for {zone_id}")
        zone = self._zones[zone_id]
        raw = self.read_raw_signal(zone)
        normalized = self.normalize_reading(raw, zone)
        calibrated = self.apply_calibration(normalized, zone)
        confidence = self.compute_confidence(raw, zone)
        self.push_to_buffer(zone_id, calibrated, confidence)
        self.logger.info(f"Collection complete for {zone_id}")

    @trace
    def merge_readings(self) -> List[float]:
        self.logger.info(f"Merging {len(self.buffer)} readings from all zones")
        values = [r.calibrated_value for r in self.buffer]
        self.logger.debug(f"Merged values: {[f'{v:.4f}' for v in values]}")
        return values

    @trace
    def compute_variance_stats(self, values: List[float]) -> Dict[str, float]:
        self.logger.info(f"Computing variance statistics for {len(values)} readings")
        mean = sum(values) / len(values)
        stddev = statistics.stdev(values)
        self.logger.debug(f"Stats — mean: {mean:.4f}, stddev: {stddev:.4f}")
        return {"mean": mean, "stddev": stddev}

    @trace
    def range_check(self, stats: Dict[str, float], reference_zone: str):
        self.logger.info(f"Running range check, reference: {reference_zone}")
        zone = self._zones[reference_zone]
        upper_bound = zone.threshold_max * zone.calibration_factor
        self.logger.debug(f"Threshold: {upper_bound:.4f}, measured stddev: {stats['stddev']:.4f}")
        if stats["stddev"] > upper_bound:
            raise ValueError(
                f"Sensor variance exceeds threshold: stddev={stats['stddev']:.4f}, max={upper_bound:.4f}"
            )

    @trace
    def generate_report(self, stats: Dict[str, float]):
        self.logger.info(f"Generating sensor report — mean={stats['mean']:.4f}, stddev={stats['stddev']:.4f}")
        self.logger.debug("Report generation complete")

    @trace
    def run(self):
        self.logger.info("Sensor aggregation pipeline started")
        zones = ["Zone-1", "Zone-2", "Zone-3"]
        futures = [self.executor.submit(self.collect_zone_data, z) for z in zones]
        for f in futures:
            f.result()
        self.logger.info("All collectors complete — starting aggregation")
        values = self.merge_readings()
        stats = self.compute_variance_stats(values)
        self.range_check(stats, "Zone-1")
        self.generate_report(stats)
        self.executor.shutdown(wait=False)