package scan

import (
	"encoding/json"
	"net/http"

	"example.com/relay/intake/internal/bus"
)

type Scan struct {
	Reference string `json:"reference"`
	Depot     string `json:"depot"`
	ScannedAt string `json:"scanned_at"`
}

// Handler takes a scan from a courier's handheld and puts it on the bus.
func Handler(publisher *bus.Publisher) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var body Scan
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			http.Error(w, "bad scan", http.StatusBadRequest)
			return
		}
		if err := publisher.Publish(r.Context(), bus.ScannedTopic, body); err != nil {
			http.Error(w, "bus unavailable", http.StatusBadGateway)
			return
		}
		w.WriteHeader(http.StatusAccepted)
	}
}
