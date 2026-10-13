package bus

import (
	"context"
	"encoding/json"

	amqp "github.com/rabbitmq/amqp091-go"
)

// ScannedTopic is the only thing the intake API tells the rest of the system.
const ScannedTopic = "delivery.scanned"

type Publisher struct {
	connection *amqp.Connection
	channel    *amqp.Channel
}

func Open(url string) (*Publisher, error) {
	connection, err := amqp.Dial(url)
	if err != nil {
		return nil, err
	}
	channel, err := connection.Channel()
	if err != nil {
		return nil, err
	}
	return &Publisher{connection: connection, channel: channel}, nil
}

func (p *Publisher) Publish(ctx context.Context, topic string, payload any) error {
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return p.channel.PublishWithContext(ctx, "", topic, false, false, amqp.Publishing{
		ContentType: "application/json",
		Body:        body,
	})
}

func (p *Publisher) Close() { _ = p.connection.Close() }
