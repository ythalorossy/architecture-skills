package main

import (
	"log"
	"net/http"
	"os"

	"github.com/go-chi/chi/v5"

	"example.com/relay/intake/internal/bus"
	"example.com/relay/intake/internal/scan"
)

func main() {
	publisher, err := bus.Open(os.Getenv("BUS_URL"))
	if err != nil {
		log.Fatal(err)
	}
	defer publisher.Close()

	router := chi.NewRouter()
	router.Post("/scans", scan.Handler(publisher))
	router.Get("/healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusOK) })

	log.Fatal(http.ListenAndServe(":8080", router))
}
