from django.core.management.base import BaseCommand
from NelsaApp.models import Route, Schedule


class Command(BaseCommand):
    help = 'Sync all schedule prices with their route base prices'

    def handle(self, *args, **options):
        self.stdout.write('Starting route price synchronization...')
        
        updated_count = 0
        total_schedules = Schedule.objects.count()
        
        for route in Route.objects.all():
            # Update all schedules for this route
            schedules_updated = Schedule.objects.filter(route=route).update(price=route.price)
            updated_count += schedules_updated
            
            if schedules_updated > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Updated {schedules_updated} schedule(s) for route {route.start_location} → {route.end_location} '
                        f'with price {route.price} FCFA'
                    )
                )
        
        self.stdout.write(
            self.style.SUCCESS(
                f'Price synchronization completed! Updated {updated_count} out of {total_schedules} schedules.'
            )
        ) 