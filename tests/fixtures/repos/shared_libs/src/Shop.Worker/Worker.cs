using Shop.Core;

namespace Shop.Worker;

public class Worker : BackgroundService
{
    private readonly OrderService _orders = new();

    protected override Task ExecuteAsync(CancellationToken stoppingToken) => Task.CompletedTask;
}
